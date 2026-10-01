from __future__ import annotations

import math
from decimal import Decimal

from research_lab.engine import Account, Replay, entry_fee

CANDIDATES = (
    "adaptive_baseline",
    "adaptive_market_blend",
    "adaptive_calibrated",
    "adaptive_calibrated_guarded",
)
TEMPERATURE_COEFFICIENT = 0.7459916645763038
MARKET_BLEND_WEIGHT = 0.5
MAX_BINARY_SPREAD = Decimal("0.06")
ADVERSE_SLIPPAGE = Decimal("0.02")
MIN_DEPTH_MULTIPLE = 2


def _clamp(probability: float) -> float:
    return min(0.999999, max(0.000001, probability))


def _logit(probability: float) -> float:
    p = _clamp(probability)
    return math.log(p / (1 - p))


def _sigmoid(value: float) -> float:
    if value >= 0:
        x = math.exp(-value)
        return 1 / (1 + x)
    x = math.exp(value)
    return x / (1 + x)


def calibrated_probability(probability: float) -> float:
    return _sigmoid(TEMPERATURE_COEFFICIENT * _logit(probability))


def blended_probability(model_probability: float, market_probability: float) -> float:
    return _sigmoid((1 - MARKET_BLEND_WEIGHT) * _logit(model_probability)
                    + MARKET_BLEND_WEIGHT * _logit(market_probability))


class CandidateEngine:
    """Four isolated accounts sharing receipt-ordered market state and execution rules."""

    def __init__(self, replay: Replay, guard_quotes=None):
        self.replay = replay
        self.guard_quotes = guard_quotes or {}

    @classmethod
    def from_seed(cls, seed: Replay):
        replay = Replay(seed.cfg, allowed_tickers=seed.allowed_tickers)
        replay.state = seed.state
        replay.accounts = {name: Account(name, Decimal(seed.cfg.bankroll)) for name in CANDIDATES}
        replay.last_decision_second = seed.last_decision_second
        replay.last_ns = seed.last_ns
        replay.event_count = 0
        replay.synthetic = False
        return cls(replay)

    def feed(self, event):
        replay = self.replay
        if event.received_ns < replay.last_ns:
            raise ValueError("Replay requires local receipt order")
        replay.last_ns = event.received_ns
        replay.event_count += 1
        replay.synthetic |= bool(event.payload.get("synthetic"))
        replay.state.apply(event)
        for account in replay.accounts.values():
            replay._fill_due(account, event.received_ns)
            replay._settle(account, event.received_ns)
        second = event.received_ns // 1_000_000_000
        if second != replay.last_decision_second:
            replay.last_decision_second = second
            for ticker in replay.state.markets:
                if replay.allowed_tickers is not None and ticker not in replay.allowed_tickers:
                    continue
                for account in replay.accounts.values():
                    self._decide(account, ticker, event.received_ns)

    def _reject_guard(self, account, ticker, reason):
        account.reject(reason)
        self.guard_quotes.pop(ticker, None)

    def _decide(self, account, ticker, now):
        replay, cfg = self.replay, self.replay.cfg
        if ticker in account.traded or ticker in account.pending or account.attempts.get(ticker, 0) >= 3:
            return
        meta = replay.state.metadata(ticker)
        if (not meta or replay.state.markets[ticker].get("result")
                or replay.state.markets[ticker].get("status") != "active"):
            return
        seconds_left = (meta[2] - now) / 1e9
        if not cfg.min_seconds_left <= seconds_left <= cfg.max_seconds_left:
            return
        if not replay.state.fee_supported(cfg, ticker, now):
            account.reject("missing_or_unsupported_series_fees")
            return
        if now - account.last_attempt.get(ticker, 0) < 10_000_000_000:
            return
        book = replay._fresh_book(ticker, now)
        if book is None:
            account.reject("stale_or_invalid_book")
            return
        fair = replay.state.forecast(ticker, now, cfg, adaptive=True)
        if fair is None:
            account.reject("missing_or_stale_forecast_inputs")
            return
        yes_ask, no_ask = book.best_ask("yes"), book.best_ask("no")
        if yes_ask is None or no_ask is None:
            account.reject("missing_two_sided_quote")
            return

        raw_yes = fair["yes_probability"]
        market_yes = float((yes_ask + Decimal(1) - no_ask) / 2)
        if account.name == "adaptive_market_blend":
            model_yes = blended_probability(raw_yes, market_yes)
            transform = "50_50_log_odds_market_blend"
        elif account.name in ("adaptive_calibrated", "adaptive_calibrated_guarded"):
            model_yes = calibrated_probability(raw_yes)
            transform = "symmetric_temperature_scaling"
        else:
            model_yes = raw_yes
            transform = "unchanged_adaptive"

        binary_spread = yes_ask + no_ask - Decimal(1)
        guarded = account.name == "adaptive_calibrated_guarded"
        if guarded and (binary_spread < 0 or binary_spread > MAX_BINARY_SPREAD):
            self._reject_guard(account, ticker, "guard_spread")
            return

        choices = []
        for side in ("yes", "no"):
            price = book.best_ask(side)
            probability = model_yes if side == "yes" else 1 - model_yes
            edge = probability - float(price + entry_fee(price, 1, cfg))
            choices.append((edge, side, price, probability))
        edge, side, price, probability = max(choices)
        if edge < cfg.min_edge:
            if guarded:
                self.guard_quotes.pop(ticker, None)
            account.reject("insufficient_net_edge")
            return

        budget = min(Decimal(cfg.risk_per_market), account.cash - account.reserved)
        count = int(budget / price)
        while count and price * count + entry_fee(price, count, cfg) > budget:
            count -= 1
        if count < 1:
            if guarded:
                self.guard_quotes.pop(ticker, None)
            account.reject("insufficient_cash")
            return

        stressed_edge = None
        if guarded:
            stressed_price = price + ADVERSE_SLIPPAGE
            if stressed_price >= 1:
                self._reject_guard(account, ticker, "guard_adverse_slippage")
                return
            stressed_edge = probability - float(stressed_price + entry_fee(stressed_price, 1, cfg))
            if stressed_edge < cfg.min_edge:
                self._reject_guard(account, ticker, "guard_adverse_slippage")
                return
            levels = book.asks(side)
            if not levels or levels[0][1] < count * MIN_DEPTH_MULTIPLE:
                self._reject_guard(account, ticker, "guard_depth")
                return
            second = now // 1_000_000_000
            previous = self.guard_quotes.get(ticker)
            self.guard_quotes[ticker] = {"second": second, "side": side, "price": price}
            if (not previous or previous["second"] != second - 1 or previous["side"] != side
                    or abs(previous["price"] - price) > Decimal("0.01")):
                account.reject("guard_persistence")
                return

        reserve = price * count + entry_fee(price, count, cfg)
        order = {
            "ticker": ticker, "side": side, "limit": price, "quantity": count,
            "created_ns": now, "arrival_ns": now + cfg.latency_ms * 1_000_000,
            "reservation": reserve, "probability": probability, "edge": edge,
            "forecast": fair, "status": "pending", "raw_model_probability": raw_yes,
            "market_yes_probability": market_yes, "probability_transform": transform,
            "quoted_binary_spread": binary_spread, "stressed_edge": stressed_edge,
        }
        account.pending[ticker] = order
        account.reserved += reserve
        account.last_attempt[ticker] = now
        account.attempts[ticker] = account.attempts.get(ticker, 0) + 1
        account.orders.append(order)
        account.decisions.append({
            "ticker": ticker, "at_ns": now, "side": side, "probability": probability,
            "net_edge": edge, "price": float(price), "forecast": fair,
            "raw_model_probability": raw_yes, "market_yes_probability": market_yes,
            "probability_transform": transform, "quoted_binary_spread": binary_spread,
            "stressed_edge": stressed_edge,
        })

    def results(self):
        return self.replay.results()
