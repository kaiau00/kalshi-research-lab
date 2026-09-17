from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .storage import Event


def epoch_ns(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1e9)


def number(value):
    x = float(value)
    if not math.isfinite(x):
        raise ValueError("Nonfinite value")
    return x


@dataclass
class Book:
    # Always store YES bids and NO bids in their own outcome price scale.
    yes: dict[Decimal, Decimal] = field(default_factory=dict)
    no: dict[Decimal, Decimal] = field(default_factory=dict)
    at_ns: int = 0
    valid: bool = False

    def asks(self, side):
        opposite = self.no if side == "yes" else self.yes
        return sorted((Decimal(1) - p, q) for p, q in opposite.items() if q > 0)

    def best_ask(self, side):
        levels = self.asks(side)
        return levels[0][0] if levels else None


class MarketState:
    def __init__(self):
        self.markets = {}
        self.series = None
        self.books: dict[str, Book] = {}
        self.seq: dict[tuple[str, int], int] = {}
        self.index = deque(maxlen=7200)  # (source_second, price, received_ns)
        self.last_index_source = -1
        self.quality = {"gaps": 0, "malformed": 0, "clock_adjustments": 0}

    def invalidate(self):
        for book in self.books.values():
            book.valid = False
        self.seq.clear()

    def apply(self, event: Event):
        p = event.payload
        if "_clock_adjustment_received_ns" in p:
            self.quality["clock_adjustments"] += 1
            self.invalidate()
            return
        if event.kind == 'series':
            self.series = p['series']
        elif event.kind == "market":
            m = p["market"]
            self.markets[m["ticker"]] = m
        elif event.kind == "gap":
            self.quality["gaps"] += 1
            self.invalidate()
        elif event.kind == "ws":
            try:
                self._ws(event)
            except (ValueError, KeyError, TypeError, ArithmeticError):
                self.quality["malformed"] += 1
                self.invalidate()

    def _ws(self, event):
        frame = event.payload["frame"]
        typ = frame.get("type")
        if typ not in ("orderbook_snapshot", "orderbook_delta", "cfbenchmarks_value"):
            return
        session = event.payload["session"]
        if "sid" in frame and "seq" in frame:
            key = (session, int(frame["sid"]))
            seq = int(frame["seq"])
            prev = self.seq.get(key)
            if prev is not None and seq <= prev:
                return
            if prev is not None and seq != prev + 1:
                self.quality["gaps"] += 1
                self.invalidate()
            self.seq[key] = seq
        msg = frame["msg"]
        if typ == "cfbenchmarks_value":
            if msg.get("index_id") != "BRTI":
                return
            raw = msg["data"]
            data = json.loads(raw) if isinstance(raw, str) else raw
            sec = int(number(data["time"]) / 1000)
            price = number(data["value"])
            if price <= 0 or sec <= self.last_index_source:
                return
            self.index.append((sec, price, event.received_ns))
            self.last_index_source = sec
            return
        ticker = msg["market_ticker"]
        book = self.books.setdefault(ticker, Book())
        convention = event.payload.get("book_convention")
        if convention != "yes_price":
            raise ValueError("Unknown book price convention")
        if typ == "orderbook_snapshot":
            levels = {}
            for side in ("yes", "no"):
                levels[side] = {}
                # Live snapshots omit sides with no depth, including both at rollover.
                raw_levels = msg.get(side + "_dollars_fp", [])
                if not isinstance(raw_levels, list):
                    raise ValueError("Invalid snapshot levels")
                for raw_price, raw_count in raw_levels:
                    price, count = Decimal(str(raw_price)), Decimal(str(raw_count))
                    if not price.is_finite() or not count.is_finite() or not 0 < price < 1 or count < 0:
                        raise ValueError("Invalid depth")
                    if side == "no":
                        price = 1 - price
                    if count:
                        levels[side][price] = count
            book.yes, book.no = levels["yes"], levels["no"]
            book.valid = True
        else:
            if not book.valid:
                return
            side = msg["side"]
            if side not in ("yes", "no"):
                raise ValueError("Invalid side")
            price = Decimal(str(msg["price_dollars"]))
            change = Decimal(str(msg["delta_fp"]))
            if not price.is_finite() or not change.is_finite() or not 0 < price < 1:
                raise ValueError("Invalid delta")
            if side == "no":
                price = 1 - price
            levels = getattr(book, side)
            count = levels.get(price, Decimal(0)) + change
            if count < 0:
                raise ValueError("Negative depth")
            if count:
                levels[price] = count
            else:
                levels.pop(price, None)
        book.at_ns = event.received_ns
        if book.yes and book.no and max(book.yes) + max(book.no) >= 1:
            book.valid = False

    def metadata(self, ticker):
        m = self.markets.get(ticker, {})
        try:
            if not ticker.startswith("KXBTC15M-") or m.get("strike_type") not in ("greater", "greater_or_equal"):
                return None
            if "BRTI" not in m.get("rules_primary", "") or "average" not in m.get("rules_primary", ""):
                return None
            if str(m.get('custom_strike', {}).get('round_digits')) != '2':
                return None
            strike = number(m["floor_strike"])
            start, close = epoch_ns(m["open_time"]), epoch_ns(m["close_time"])
            if strike <= 0 or close - start != 900_000_000_000:
                return None
            return strike, start, close
        except (KeyError, ValueError, TypeError):
            return None

    def fee_supported(self, cfg):
        try:
            return (self.series is not None and self.series.get('ticker') == 'KXBTC15M'
                    and self.series.get('fee_type') == 'quadratic'
                    and Decimal(str(self.series['fee_multiplier'])) > 0
                    and Decimal(str(self.series['fee_multiplier'])) * Decimal('.07')
                    <= Decimal(cfg.taker_fee_rate))
        except (ValueError, KeyError, TypeError, ArithmeticError):
            return False

    def forecast(self, ticker, now_ns, cfg, *, adaptive=False):
        meta = self.metadata(ticker)
        if not meta or not self.index:
            return None
        strike, start, close = meta
        if not start <= now_ns < close:
            return None
        last_sec, spot, received = self.index[-1]
        if now_ns - received > cfg.max_index_age_ms * 1_000_000:
            return None
        if abs(now_ns // 1_000_000_000 - last_sec) > cfg.max_index_age_ms / 1000:
            return None
        returns = []
        recent_returns = []
        prev = None
        for sec, price, _ in self.index:
            if prev is not None and sec - prev[0] == 1 and sec >= last_sec - cfg.slow_window_seconds:
                r = math.log(price / prev[1])
                returns.append(r)
                if sec >= last_sec - cfg.fast_window_seconds:
                    recent_returns.append(r)
            prev = (sec, price)
        if len(returns) < cfg.min_returns:
            return None
        variance = sum(r * r for r in returns) / len(returns)
        if adaptive:
            if len(recent_returns) < min(cfg.min_returns, cfg.fast_window_seconds):
                return None
            variance = 0.7 * sum(r * r for r in recent_returns) / len(recent_returns) + 0.3 * variance
        # No forced volatility floor; a frozen feed cannot become an invented probability.
        if variance <= 0:
            return None
        close_sec = close // 1_000_000_000
        # Settlement uses [close-60s, close), verified against 15 official outcomes.
        # The WebSocket quarter-hour accumulation field uses a different boundary.
        targets = range(close_sec - 60, close_sec)
        observed = {s: p for s, p, _ in self.index if close_sec - 60 <= s < close_sec}
        past_targets = [s for s in targets if s <= last_sec]
        if any(s not in observed for s in past_targets):
            return None
        future = [s for s in targets if s > last_sec]
        mean = (sum(observed[s] for s in past_targets) + len(future) * spot) / 60
        # Brownian covariance of future averaged prices, conditional on latest known tick.
        covariance_sum = sum(min(a - last_sec, b - last_sec) for a in future for b in future)
        sigma = spot * math.sqrt(variance * covariance_sum) / 60
        if sigma <= 0:
            return None
        # Half-cent continuity correction for a >= threshold with cent-rounded settlement.
        threshold = strike - 0.005 if self.markets[ticker]["strike_type"] == "greater_or_equal" else strike + 0.005
        z = (mean - threshold) / sigma
        prob = 0.5 * (1 + math.erf(z / math.sqrt(2)))
        return {"yes_probability": min(0.999, max(0.001, prob)), "z": z,
                "sigma_dollars": sigma, "expected_average": mean,
                "observed_settlement_seconds": len(past_targets), "spot": spot,
                "seconds_left": (close - now_ns) / 1e9}
