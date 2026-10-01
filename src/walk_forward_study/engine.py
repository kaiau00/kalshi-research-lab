from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal

from candidate_study.engine import TEMPERATURE_COEFFICIENT
from research_lab.engine import Account, Replay, entry_fee

MODELS = ("raw", "calibrated", "blend25", "blend50", "blend75")
EDGES = (0.04, 0.06, 0.08, 0.10)


def configurations():
    rows = []
    for model in MODELS:
        for edge in EDGES:
            rows.append({"name": f"signal_{model}_e{int(edge * 100):02d}", "model": model,
                         "min_edge": edge, "min_seconds": 5, "max_seconds": 300,
                         "max_spread": None, "persistence": 1})
    for model in MODELS:
        for maximum in (120, 180):
            rows.append({"name": f"window_{model}_e06_30_{maximum}", "model": model,
                         "min_edge": 0.06, "min_seconds": 30, "max_seconds": maximum,
                         "max_spread": None, "persistence": 1})
    for model in ("calibrated", "blend50"):
        for spread in (Decimal("0.03"), Decimal("0.05")):
            rows.append({"name": f"spread_{model}_e06_30_180_s{int(spread * 100):02d}",
                         "model": model, "min_edge": 0.06, "min_seconds": 30,
                         "max_seconds": 180, "max_spread": str(spread), "persistence": 1})
    for model in ("calibrated", "blend50"):
        for spread in (Decimal("0.03"), Decimal("0.05"), Decimal("0.07")):
            rows.append({"name": f"persist_{model}_e06_30_180_s{int(spread * 100):02d}",
                         "model": model, "min_edge": 0.06, "min_seconds": 30,
                         "max_seconds": 180, "max_spread": str(spread), "persistence": 2})
    if len(rows) != 40 or len({row["name"] for row in rows}) != 40:
        raise RuntimeError("Study 004 configuration definition changed")
    return tuple(rows)


CONFIGS = configurations()
CONFIG_BY_NAME = {row["name"]: row for row in CONFIGS}
REFERENCE = "signal_raw_e04"


def _clamp(probability):
    return min(0.999999, max(0.000001, probability))


def _logit(probability):
    p = _clamp(probability)
    return math.log(p / (1 - p))


def _sigmoid(value):
    if value >= 0:
        x = math.exp(-value)
        return 1 / (1 + x)
    x = math.exp(value)
    return x / (1 + x)


def model_probability(model, raw_probability, market_probability):
    if model == "raw":
        return raw_probability
    if model == "calibrated":
        return _sigmoid(TEMPERATURE_COEFFICIENT * _logit(raw_probability))
    if model.startswith("blend"):
        weight = int(model.removeprefix("blend")) / 100
        return _sigmoid((1 - weight) * _logit(raw_probability)
                        + weight * _logit(market_probability))
    raise ValueError("Unknown probability model")


def fast_rms_bps(index):
    if len(index) < 2:
        return None
    last_sec = index[-1][0]
    values = []
    previous = None
    for sec, price, _ in index:
        if previous and sec - previous[0] == 1 and sec >= last_sec - 60:
            values.append(math.log(price / previous[1]))
        previous = (sec, price)
    if len(values) < 30:
        return None
    return math.sqrt(sum(value * value for value in values) / len(values)) * 10_000


def volatility_regime(value):
    if value is None:
        return "unknown"
    if value < 0.5:
        return "low"
    if value <= 1.5:
        return "medium"
    return "high"


class WalkForwardEngine:
    def __init__(self, replay=None, persistence=None, active=None, common_rejected=None,
                 pending_accounts=None, position_accounts=None):
        self.replay = replay or Replay()
        if replay is None:
            self.replay.accounts = {row["name"]: Account(row["name"], Decimal("100.00"))
                                    for row in CONFIGS}
            for account in self.replay.accounts.values():
                account.study_stats = {"submitted": 0, "filled": 0, "fees": Decimal(0),
                                       "peak": 100.0, "max_drawdown": 0.0}
        self.persistence = persistence or {}
        self.active = active or set()
        self.common_rejected = common_rejected or {}
        self.pending_accounts = pending_accounts or set()
        self.position_accounts = position_accounts or set()

    def state(self):
        return {"replay": self.replay, "persistence": self.persistence,
                "active": self.active, "common_rejected": self.common_rejected,
                "pending_accounts": self.pending_accounts, "position_accounts": self.position_accounts}

    @classmethod
    def from_state(cls, value):
        return cls(value["replay"], value["persistence"], value["active"], value["common_rejected"],
                   value["pending_accounts"], value["position_accounts"])

    def _reject_all(self, reason):
        self.common_rejected[reason] = self.common_rejected.get(reason, 0) + 1

    def _compact(self, account):
        stats = account.study_stats
        for order in account.orders:
            if order.get("status") in ("filled", "partial_ioc") and not order.get("_study_counted"):
                stats["filled"] += 1
                stats["fees"] += order["fees"]
                order["_study_counted"] = True
        for point in account.equity:
            stats["peak"] = max(stats["peak"], point["cost_equity"])
            stats["max_drawdown"] = max(stats["max_drawdown"], stats["peak"] - point["cost_equity"])
        account.equity.clear()
        account.decisions.clear()
        account.orders[:] = [order for order in account.orders
                             if order["status"] == "pending" or order["ticker"] in account.positions]

    def feed(self, event):
        replay = self.replay
        if event.received_ns < replay.last_ns:
            raise ValueError("Replay requires local receipt order")
        replay.last_ns = event.received_ns
        replay.event_count += 1
        replay.synthetic |= bool(event.payload.get("synthetic"))
        replay.state.apply(event)
        if event.kind == "market":
            market = event.payload["market"]
            if market.get("status") == "active" and not market.get("result"):
                self.active.add(market["ticker"])
            else:
                self.active.discard(market["ticker"])
        for name in tuple(self.pending_accounts):
            account = replay.accounts[name]
            arrival = min(order["arrival_ns"] for order in account.pending.values())
            if event.received_ns >= arrival:
                replay._fill_due(account, event.received_ns)
                if account.positions:
                    self.position_accounts.add(name)
                if not account.pending:
                    self.pending_accounts.discard(name)
                self._compact(account)
        if event.kind == "market":
            for name in tuple(self.position_accounts):
                account = replay.accounts[name]
                replay._settle(account, event.received_ns)
                if not account.positions:
                    self.position_accounts.discard(name)
                self._compact(account)
        second = event.received_ns // 1_000_000_000
        if second == replay.last_decision_second:
            return
        replay.last_decision_second = second
        for ticker in tuple(self.active):
            opportunity = self._opportunity(ticker, event.received_ns)
            if opportunity:
                self._evaluate(ticker, event.received_ns, opportunity)

    def _opportunity(self, ticker, now):
        replay, cfg = self.replay, self.replay.cfg
        meta = replay.state.metadata(ticker)
        if not meta or replay.state.markets[ticker].get("status") != "active":
            return None
        seconds_left = (meta[2] - now) / 1e9
        if not 5 <= seconds_left <= 300:
            return None
        if not replay.state.fee_supported(cfg, ticker, now):
            self._reject_all("missing_or_unsupported_series_fees")
            return None
        book = replay._fresh_book(ticker, now)
        if book is None:
            self._reject_all("stale_or_invalid_book")
            return None
        fair = replay.state.forecast(ticker, now, cfg, adaptive=True)
        if fair is None:
            self._reject_all("missing_or_stale_forecast_inputs")
            return None
        yes_ask, no_ask = book.best_ask("yes"), book.best_ask("no")
        if yes_ask is None or no_ask is None:
            self._reject_all("missing_two_sided_quote")
            return None
        return {"book": book, "fair": fair, "seconds_left": seconds_left,
                "yes_ask": yes_ask, "no_ask": no_ask,
                "market_yes": float((yes_ask + Decimal(1) - no_ask) / 2),
                "spread": yes_ask + no_ask - Decimal(1),
                "fast_rms_bps": fast_rms_bps(replay.state.index)}

    def _evaluate(self, ticker, now, opportunity):
        for name, account in self.replay.accounts.items():
            config = CONFIG_BY_NAME[name]
            if (ticker in account.traded or ticker in account.pending
                    or account.attempts.get(ticker, 0) >= 3):
                continue
            seconds_left = opportunity["seconds_left"]
            if not config["min_seconds"] <= seconds_left <= config["max_seconds"]:
                continue
            if now - account.last_attempt.get(ticker, 0) < 10_000_000_000:
                continue
            spread_cap = Decimal(config["max_spread"]) if config["max_spread"] else None
            if spread_cap is not None and not 0 <= opportunity["spread"] <= spread_cap:
                account.reject("spread_filter")
                self.persistence.pop((name, ticker), None)
                continue
            probability_yes = model_probability(config["model"],
                opportunity["fair"]["yes_probability"], opportunity["market_yes"])
            choices = []
            for side in ("yes", "no"):
                price = opportunity[side + "_ask"]
                probability = probability_yes if side == "yes" else 1 - probability_yes
                edge = probability - float(price + entry_fee(price, 1, self.replay.cfg))
                choices.append((edge, side, price, probability))
            edge, side, price, probability = max(choices)
            if edge < config["min_edge"]:
                account.reject("insufficient_net_edge")
                self.persistence.pop((name, ticker), None)
                continue
            budget = min(Decimal(self.replay.cfg.risk_per_market), account.cash - account.reserved)
            count = int(budget / price)
            while count and price * count + entry_fee(price, count, self.replay.cfg) > budget:
                count -= 1
            if count < 1:
                account.reject("insufficient_cash")
                self.persistence.pop((name, ticker), None)
                continue
            if config["persistence"] == 2:
                key = (name, ticker)
                previous = self.persistence.get(key)
                second = now // 1_000_000_000
                self.persistence[key] = {"second": second, "side": side, "price": price}
                if (not previous or previous["second"] != second - 1 or previous["side"] != side
                        or abs(previous["price"] - price) > Decimal("0.01")):
                    account.reject("persistence_filter")
                    continue
            reserve = price * count + entry_fee(price, count, self.replay.cfg)
            order = {"ticker": ticker, "side": side, "limit": price, "quantity": count,
                     "created_ns": now, "arrival_ns": now + self.replay.cfg.latency_ms * 1_000_000,
                     "reservation": reserve, "probability": probability, "edge": edge,
                     "forecast": opportunity["fair"], "status": "pending",
                     "model": config["model"], "market_yes_probability": opportunity["market_yes"],
                     "quoted_binary_spread": opportunity["spread"],
                     "fast_rms_bps": opportunity["fast_rms_bps"]}
            account.pending[ticker] = order
            account.reserved += reserve
            account.last_attempt[ticker] = now
            account.attempts[ticker] = account.attempts.get(ticker, 0) + 1
            account.orders.append(order)
            account.study_stats["submitted"] += 1
            self.pending_accounts.add(name)

    def _stressed_pnl(self, trade, slip):
        price = min(Decimal(1), trade["fill_price"] + slip)
        cost = price * trade["filled"] + entry_fee(price, trade["filled"], self.replay.cfg)
        return trade["payout"] - cost

    def _market_blocks(self):
        ordered = []
        dates = set()
        for ticker in self.replay.state.markets:
            meta = self.replay.state.metadata(ticker)
            market = self.replay.state.markets[ticker]
            if meta and market.get("status") == "finalized" and market.get("result") in ("yes", "no"):
                ordered.append((meta[2], ticker))
                dates.add(datetime.fromtimestamp(meta[2] / 1e9, timezone.utc).date().isoformat())
        ordered.sort()
        blocks = {ticker: min(4, index * 5 // max(1, len(ordered)))
                  for index, (_, ticker) in enumerate(ordered)}
        return blocks, sorted(dates)

    def results(self):
        blocks, observed_days = self._market_blocks()
        output = {"synthetic": self.replay.synthetic, "events_replayed": self.replay.event_count,
                  "receipt_cutoff_ns": self.replay.last_ns, "quality": self.replay.state.quality,
                  "observed_utc_days": observed_days, "common_rejections": self.common_rejected,
                  "accounts": {}}
        for name, account in self.replay.accounts.items():
            closed = account.closed
            pnls = [trade["pnl"] for trade in closed]
            pnl = sum(pnls, Decimal(0))
            winners = sorted((value for value in pnls if value > 0), reverse=True)
            daily = {day: 0.0 for day in observed_days}
            block_pnl = [0.0] * 5
            regimes = {key: {"settled": 0, "pnl": 0.0} for key in ("low", "medium", "high", "unknown")}
            brier = []
            logloss = []
            for trade in closed:
                daily[trade["settled_day"]] = daily.get(trade["settled_day"], 0.0) + float(trade["pnl"])
                if trade["ticker"] in blocks:
                    block_pnl[blocks[trade["ticker"]]] += float(trade["pnl"])
                regime = volatility_regime(trade.get("fast_rms_bps"))
                regimes[regime]["settled"] += 1
                regimes[regime]["pnl"] += float(trade["pnl"])
                label = float(trade["won"])
                probability = _clamp(trade["probability"])
                brier.append((probability - label) ** 2)
                logloss.append(-(label * math.log(probability) + (1 - label) * math.log(1 - probability)))
            stats = account.study_stats
            stressed = {str(cents): float(sum((self._stressed_pnl(t, Decimal(cents) / 100)
                                               for t in closed), Decimal(0))) for cents in (1, 2)}
            output["accounts"][name] = {
                "config": CONFIG_BY_NAME[name], "cash": float(account.cash),
                "realized_net_pnl": float(pnl), "pnl_without_top_three_winners": float(pnl - sum(winners[:3], Decimal(0))),
                "stressed_pnl": stressed, "settled_markets": len(closed),
                "filled_markets": stats["filled"], "orders_submitted": stats["submitted"],
                "fill_rate": stats["filled"] / stats["submitted"] if stats["submitted"] else None,
                "fees_paid": float(stats["fees"]), "unresolved_markets": len(account.positions),
                "pending_orders": len(account.pending), "max_drawdown_cost_basis": stats["max_drawdown"],
                "daily_pnl": daily, "positive_day_share": (sum(value > 0 for value in daily.values()) / len(daily)
                                                               if daily else None),
                "block_pnl": block_pnl, "positive_blocks": sum(value > 0 for value in block_pnl),
                "brier_score": sum(brier) / len(brier) if brier else None,
                "binary_log_loss": sum(logloss) / len(logloss) if logloss else None,
                "volatility_regimes": regimes, "rejections": account.rejected,
                "open_cost": float(sum((p["cost"] for p in account.positions.values()), Decimal(0))),
            }
        reference_loss = output["accounts"][REFERENCE]["binary_log_loss"]
        eligible = []
        for name, row in output["accounts"].items():
            row["promotion_eligible"] = bool(
                row["settled_markets"] >= 100 and row["realized_net_pnl"] > 0
                and row["pnl_without_top_three_winners"] > 0 and row["stressed_pnl"]["2"] > 0
                and row["positive_blocks"] >= 4 and (row["positive_day_share"] or 0) > 0.5
                and row["max_drawdown_cost_basis"] <= 20 and row["binary_log_loss"] is not None
                and reference_loss is not None and row["binary_log_loss"] <= reference_loss)
            if row["promotion_eligible"]:
                eligible.append(name)
        eligible.sort(key=lambda name: (
            min(output["accounts"][name]["block_pnl"]),
            output["accounts"][name]["pnl_without_top_three_winners"],
            -output["accounts"][name]["binary_log_loss"],
            output["accounts"][name]["settled_markets"]), reverse=True)
        output["selection"] = {"eligible": eligible, "winner": eligible[0] if eligible else None,
                               "development_only": True, "requires_new_prospective_study": True}
        return output
