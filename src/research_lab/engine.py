from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal

from .market import MarketState
from .settings import Experiment

STRATEGIES = ("basic_fair_value", "tail_underdog", "adaptive_volatility")


def entry_fee(price: Decimal, quantity: int, cfg: Experiment) -> Decimal:
    # Integer quantity and one aggregate price level per simulated IOC. For direct
    # accounts, ceil(cost + ceil_6dp(model_fee)) - cost matches final balance precision.
    cost = price * quantity
    fee = (Decimal(cfg.taker_fee_rate) * quantity * price * (1 - price)).quantize(
        Decimal("0.000001"), rounding=ROUND_CEILING)
    return (cost + fee).quantize(Decimal(cfg.balance_precision), rounding=ROUND_CEILING) - cost


@dataclass
class Account:
    name: str
    cash: Decimal
    reserved: Decimal = Decimal(0)
    pending: dict = field(default_factory=dict)
    positions: dict = field(default_factory=dict)
    traded: set = field(default_factory=set)
    orders: list = field(default_factory=list)
    closed: list = field(default_factory=list)
    decisions: list = field(default_factory=list)
    equity: list = field(default_factory=list)
    rejected: dict = field(default_factory=dict)
    last_attempt: dict = field(default_factory=dict)
    attempts: dict = field(default_factory=dict)

    def reject(self, reason):
        self.rejected[reason] = self.rejected.get(reason, 0) + 1


class Replay:
    """Streaming paper accounts; only previously received events can affect decisions."""

    def __init__(self, cfg=None, allowed_tickers=None):
        self.cfg = cfg or Experiment()
        self.allowed_tickers = allowed_tickers
        self.state = MarketState()
        self.accounts = {name: Account(name, Decimal(self.cfg.bankroll)) for name in STRATEGIES}
        self.last_decision_second = -1
        self.last_ns = 0
        self.event_count = 0
        self.synthetic = False

    def feed(self, event):
        if event.received_ns < self.last_ns:
            raise ValueError("Replay requires local receipt order")
        self.last_ns = event.received_ns
        self.event_count += 1
        self.synthetic |= bool(event.payload.get("synthetic"))
        self.state.apply(event)
        for account in self.accounts.values():
            self._fill_due(account, event.received_ns)
            self._settle(account, event.received_ns)
        # Evaluate all models on identical one-second decision opportunities.
        second = event.received_ns // 1_000_000_000
        if second != self.last_decision_second:
            self.last_decision_second = second
            for ticker in self.state.markets:
                if self.allowed_tickers is not None and ticker not in self.allowed_tickers:
                    continue
                for account in self.accounts.values():
                    self._decide(account, ticker, event.received_ns)

    def _fresh_book(self, ticker, now):
        book = self.state.books.get(ticker)
        if not book or not book.valid or now - book.at_ns > self.cfg.max_book_age_ms * 1_000_000:
            return None
        return book

    def _decide(self, account, ticker, now):
        if ticker in account.traded or ticker in account.pending or account.attempts.get(ticker, 0) >= 3:
            return
        meta = self.state.metadata(ticker)
        if not meta or self.state.markets[ticker].get("result"):
            return
        seconds_left = (meta[2] - now) / 1e9
        if not self.cfg.min_seconds_left <= seconds_left <= self.cfg.max_seconds_left:
            return
        if not self.state.fee_supported(self.cfg):
            account.reject('missing_or_unsupported_series_fees')
            return
        if now - account.last_attempt.get(ticker, 0) < 10_000_000_000:
            return
        book = self._fresh_book(ticker, now)
        if book is None:
            account.reject("stale_or_invalid_book")
            return
        fair = self.state.forecast(ticker, now, self.cfg, adaptive=account.name == "adaptive_volatility")
        if fair is None:
            account.reject("missing_or_stale_forecast_inputs")
            return
        yes_ask, no_ask = book.best_ask("yes"), book.best_ask("no")
        if yes_ask is None or no_ask is None:
            account.reject("missing_two_sided_quote")
            return
        sides = ("yes", "no")
        if account.name == "tail_underdog":
            if seconds_left > self.cfg.tail_max_seconds or abs(fair["z"]) > self.cfg.tail_max_z:
                account.reject("tail_filter")
                return
            if yes_ask == no_ask:
                return
            sides = ("yes" if yes_ask < no_ask else "no",)
        candidates = []
        for side in sides:
            price = book.best_ask(side)
            if account.name == "tail_underdog" and float(price) > self.cfg.tail_max_price:
                continue
            prob = fair["yes_probability"] if side == "yes" else 1 - fair["yes_probability"]
            edge = prob - float(price + entry_fee(price, 1, self.cfg))
            candidates.append((edge, side, price, prob))
        if not candidates:
            return
        edge, side, price, prob = max(candidates)
        if edge < self.cfg.min_edge:
            account.reject("insufficient_net_edge")
            return
        budget = min(Decimal(self.cfg.risk_per_market), account.cash - account.reserved)
        count = int(budget / price)
        while count and price * count + entry_fee(price, count, self.cfg) > budget:
            count -= 1
        if count < 1:
            account.reject("insufficient_cash")
            return
        reserve = price * count + entry_fee(price, count, self.cfg)
        order = {"ticker": ticker, "side": side, "limit": price, "quantity": count,
                 "created_ns": now, "arrival_ns": now + self.cfg.latency_ms * 1_000_000,
                 "reservation": reserve, "probability": prob, "edge": edge,
                 "forecast": fair, "status": "pending"}
        account.pending[ticker] = order
        account.reserved += reserve
        account.last_attempt[ticker] = now
        account.attempts[ticker] = account.attempts.get(ticker, 0) + 1
        account.orders.append(order)
        account.decisions.append({"ticker": ticker, "at_ns": now, "side": side,
                                  "probability": prob, "net_edge": edge,
                                  "price": float(price), "forecast": fair})

    def _fill_due(self, account, now):
        for ticker, order in list(account.pending.items()):
            if now < order["arrival_ns"]:
                continue
            account.reserved -= order["reservation"]
            del account.pending[ticker]
            meta = self.state.metadata(ticker)
            book = self._fresh_book(ticker, now)
            if (not meta or now >= meta[2] or self.state.markets[ticker].get("result") or not book
                    or not self.state.fee_supported(self.cfg)):
                order["status"] = "canceled_unavailable"
                continue
            # Use the book known at the first receipt event at/after arrival, only
            # its best eligible level. Discrete sampling can bias either direction.
            levels = book.asks(order["side"])
            if not levels or levels[0][0] > order["limit"]:
                order["status"] = "canceled_limit_not_marketable"
                continue
            price, available = levels[0]
            count = min(order["quantity"], int(available))
            if count <= 0:
                order["status"] = "canceled_no_integer_depth"
                continue
            fee = entry_fee(price, count, self.cfg)
            cost = price * count + fee
            if cost > order["reservation"] or cost > account.cash - account.reserved:
                order["status"] = "canceled_budget"
                continue
            account.cash -= cost
            account.traded.add(ticker)
            order.update(status="filled" if count == order["quantity"] else "partial_ioc",
                         filled=count, fill_price=price, fees=fee, cost=cost, fill_ns=now)
            account.positions[ticker] = order
            self._equity(account, now)

    def _settle(self, account, now):
        for ticker, pos in list(account.positions.items()):
            result = self.state.markets.get(ticker, {}).get("result")
            meta = self.state.metadata(ticker)
            if (result not in ("yes", "no") or not meta or now < meta[2]
                    or self.state.markets[ticker].get("status") != "finalized"):
                continue
            won = result == pos["side"]
            payout = Decimal(pos["filled"] if won else 0)
            account.cash += payout
            closed = {**pos, "result": result, "won": won, "payout": payout,
                      "pnl": payout - pos["cost"], "settled_ns": now,
                      "settled_day": datetime.fromtimestamp(now / 1e9, timezone.utc).date().isoformat()}
            account.closed.append(closed)
            del account.positions[ticker]
            self._equity(account, now)

    def _equity(self, account, now):
        # Cost equity is explicitly not a mark-to-market liquidation estimate.
        equity = account.cash + sum((p["cost"] for p in account.positions.values()), Decimal(0))
        account.equity.append({"at_ns": now, "cash": float(account.cash), "cost_equity": float(equity)})

    def results(self):
        result = {"synthetic": self.synthetic, "events_replayed": self.event_count,
                  "receipt_cutoff_ns": self.last_ns, "quality": self.state.quality,
                  "accounts": {}}
        for name, account in self.accounts.items():
            pnl = sum((p["pnl"] for p in account.closed), Decimal(0))
            fees = sum((p.get("fees", Decimal(0)) for p in account.orders), Decimal(0))
            peak, max_dd = float(self.cfg.bankroll), 0.0
            for e in account.equity:
                peak = max(peak, e["cost_equity"])
                max_dd = max(max_dd, peak - e["cost_equity"])
            daily = {}
            for p in account.closed:
                daily[p["settled_day"]] = daily.get(p["settled_day"], 0) + float(p["pnl"])
            filled = sum(o["status"] in ("filled", "partial_ioc") for o in account.orders)
            calibration = []
            for lo in range(0, 100, 10):
                rows = [p for p in account.closed if lo / 100 <= p["probability"] < (lo + 10) / 100]
                if rows:
                    calibration.append({"band": f"{lo}-{lo+10}%", "n": len(rows),
                                        "predicted": sum(p["probability"] for p in rows) / len(rows),
                                        "observed": sum(p["won"] for p in rows) / len(rows)})
            result["accounts"][name] = {
                "cash": float(account.cash), "reserved": float(account.reserved),
                "realized_net_pnl": float(pnl), "fees_paid": float(fees),
                "open_cost": float(sum((p["cost"] for p in account.positions.values()), Decimal(0))),
                "unresolved_markets": len(account.positions), "pending_orders": len(account.pending),
                "settled_markets": len(account.closed), "filled_markets": filled,
                "orders_submitted": len(account.orders), "fill_rate": filled / len(account.orders) if account.orders else None,
                "win_rate": sum(p["won"] for p in account.closed) / len(account.closed) if account.closed else None,
                "max_drawdown_cost_basis": max_dd, "daily_pnl": daily,
                "entry_calibration": calibration, "rejections": account.rejected,
                "orders": account.orders, "closed_trades": account.closed,
                "decisions": account.decisions, "equity": account.equity,
            }
        return result
