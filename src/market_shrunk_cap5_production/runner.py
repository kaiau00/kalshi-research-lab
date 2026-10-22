from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import math
import os
import time
import uuid
from decimal import Decimal
from pathlib import Path

import httpx

from historical_optimization.study import blend_probability, full_kelly_fraction
from production_execution.client import ProductionClient
from production_execution.journal import Journal, dumps, fill_count
from production_execution.runner import Runner as ReconciliationRunner
from research_lab.engine import entry_fee
from research_lab.settings import Experiment

from .registration import (
    AUTHORIZATION,
    CONFIG_REVISION,
    FUNDING_REVISION,
    HOLD_AUTHORIZATION,
    HOLD_REVISION,
    RISK_AUTHORIZATION,
    RISK_REVISION,
    STRATEGY,
    registration,
    registration_hash,
)

STARTING_CASH = Decimal("139.4648")
KELLY_MULTIPLIER = Decimal("0.50")
MAXIMUM_ALL_IN = Decimal("5.00")
FAST_VARIANCE_WEIGHT = Decimal("0.90")
MARKET_LOG_ODDS_WEIGHT = 0.25
MINIMUM_NET_EDGE = 0.005
MINIMUM_SELECTED_ASK = Decimal("0.45")
MAXIMUM_SELECTED_ASK = Decimal("0.80")
MAXIMUM_MODEL_MARKET_GAP = 0.075
MAXIMUM_BINARY_SPREAD = Decimal("0.02")
ADVERSE_PRICE_BUFFER = Decimal("0.02")
ENTRY_PAUSE_FILE = "PAUSE_ENTRIES"
COMMISSION_RECEIPT_FILE = "COMMISSIONED.json"
RUNNER_NAME = "market_shrunk_half_kelly_cap5_001"


def valid_commission_receipt(root: Path) -> bool:
    path = root / COMMISSION_RECEIPT_FILE
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        return False
    expected = {
        "strategy": STRATEGY,
        "candidate_registration_sha256": registration_hash(),
        "funding_revision": FUNDING_REVISION,
        "initial_cash": str(STARTING_CASH),
        "exchange_index": 2,
        "subaccount": 0,
    }
    return all(value.get(key) == expected_value for key, expected_value in expected.items()) and (
        isinstance(value.get("commissioned_ns"), int) and value["commissioned_ns"] > 0
    )


def quantity_for_budget(price: Decimal, budget: Decimal, cfg: Experiment) -> int:
    if budget <= 0 or not 0 < price < 1:
        return 0
    quantity = int(budget / price)
    while quantity and price * quantity + entry_fee(price, quantity, cfg) > budget:
        quantity -= 1
    return quantity


def half_kelly_target(probability: float, price: Decimal, cash: Decimal, cfg: Experiment):
    unit_cost = price + entry_fee(price, 1, cfg)
    full_kelly = full_kelly_fraction(probability, unit_cost)
    target = min(MAXIMUM_ALL_IN, cash * full_kelly * KELLY_MULTIPLIER, cash)
    return target, full_kelly


def order_payload(decision):
    price = Decimal(decision["limit"])
    quantity = int(decision["quantity"])
    reservation = Decimal(decision["reservation"])
    cfg = Experiment(bankroll="100.00", risk_per_market="5.00", min_edge=MINIMUM_NET_EDGE)
    while quantity and price * quantity + entry_fee(price, quantity, cfg) > reservation:
        quantity -= 1
    if quantity < 1:
        return None
    return {
        "ticker": decision["ticker"],
        "client_order_id": "prod-" + uuid.uuid4().hex,
        "side": "bid" if decision["side"] == "yes" else "ask",
        "price": str(price if decision["side"] == "yes" else 1 - price),
        "count": str(quantity),
        "time_in_force": "immediate_or_cancel",
        "self_trade_prevention_type": "taker_at_cross",
        "exchange_index": 2,
        "subaccount": 0,
    }


def minute_boundary(now_ns: int, close_ns: int) -> int | None:
    now_second = now_ns // 1_000_000_000
    boundary = now_second - now_second % 60
    if now_second - boundary > 3:
        return None
    seconds_left = close_ns // 1_000_000_000 - boundary
    return boundary if 5 <= seconds_left <= 300 else None


def forecast_at_completed_minute(state, ticker, boundary_second: int, now_ns: int, cfg):
    meta = state.metadata(ticker)
    if not meta or not state.index:
        return None
    strike, start_ns, close_ns = meta
    decision_ns = boundary_second * 1_000_000_000
    if not start_ns <= decision_ns < close_ns:
        return None
    latest_second, _, latest_received_ns = state.index[-1]
    if now_ns - latest_received_ns > cfg.max_index_age_ms * 1_000_000:
        return None
    cutoff = boundary_second - 1
    if latest_second < cutoff or latest_second - cutoff > 3:
        return None
    points = {
        second: price
        for second, price, _received in state.index
        if cutoff - cfg.slow_window_seconds - 1 <= second <= cutoff
    }
    spot = points.get(cutoff)
    if spot is None:
        return None
    returns = []
    recent_returns = []
    for second in range(cutoff - cfg.slow_window_seconds, cutoff + 1):
        previous = points.get(second - 1)
        current = points.get(second)
        if previous is None or current is None:
            continue
        value = math.log(current / previous)
        returns.append(value)
        if second >= cutoff - cfg.fast_window_seconds:
            recent_returns.append(value)
    if len(returns) < cfg.min_returns or len(recent_returns) < cfg.min_returns:
        return None
    slow_variance = sum(value * value for value in returns) / len(returns)
    fast_variance = sum(value * value for value in recent_returns) / len(recent_returns)
    variance = float(FAST_VARIANCE_WEIGHT) * fast_variance + (
        1 - float(FAST_VARIANCE_WEIGHT)
    ) * slow_variance
    if variance <= 0:
        return None
    close_second = close_ns // 1_000_000_000
    targets = range(close_second - 60, close_second)
    observed = {second: points[second] for second in targets if second in points}
    past_targets = [second for second in targets if second <= cutoff]
    if any(second not in observed for second in past_targets):
        return None
    future = [second for second in targets if second > cutoff]
    mean = (sum(observed[second] for second in past_targets) + len(future) * spot) / 60
    covariance_sum = sum(min(a - cutoff, b - cutoff) for a in future for b in future)
    sigma = spot * math.sqrt(variance * covariance_sum) / 60
    if sigma <= 0:
        return None
    strike_type = state.markets[ticker]["strike_type"]
    threshold = strike - 0.005 if strike_type == "greater_or_equal" else strike + 0.005
    z = (mean - threshold) / sigma
    probability = 0.5 * (1 + math.erf(z / math.sqrt(2)))
    return {
        "yes_probability": min(0.999, max(0.001, probability)),
        "z": z,
        "sigma_dollars": sigma,
        "expected_average": mean,
        "observed_settlement_seconds": len(past_targets),
        "spot": spot,
        "seconds_left": (close_ns - decision_ns) / 1e9,
        "variance_blend": "90% fast + 10% slow",
        "decision_boundary_second": boundary_second,
        "forecast_cutoff_second": cutoff,
    }


class Runner(ReconciliationRunner):
    def __init__(self, state_provider, root=None, client=None):
        if os.environ.get("LAB_MARKET_SHRUNK_CAP5_PRODUCTION_AUTHORIZATION") != AUTHORIZATION:
            raise RuntimeError("Market-shrunk production authorization token is absent")
        if os.environ.get("LAB_MARKET_SHRUNK_CAP5_RISK_AUTHORIZATION") != RISK_AUTHORIZATION:
            raise RuntimeError("Market-shrunk risk authorization token is absent")
        if os.environ.get("LAB_MARKET_SHRUNK_CAP5_HOLD_AUTHORIZATION") != HOLD_AUTHORIZATION:
            raise RuntimeError("Market-shrunk hold authorization token is absent")
        if state_provider is None:
            raise ValueError("Production market-state provider is required")
        self.state_provider = state_provider
        self.root = Path(
            root
            or os.environ.get(
                "LAB_MARKET_SHRUNK_CAP5_PRODUCTION_DIR",
                "/data/production-market-shrunk-half-kelly-cap5-001",
            )
        )
        is_new = not (self.root / "orders.sqlite3").exists()
        self.root.mkdir(parents=True, exist_ok=True)
        if is_new:
            (self.root / ENTRY_PAUSE_FILE).touch(exist_ok=True)
        self.lock = (self.root / "runner.lock").open("a")
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.cfg = Experiment(
            bankroll="100.00",
            risk_per_market="5.00",
            min_edge=MINIMUM_NET_EDGE,
            latency_ms=500,
            min_seconds_left=5,
            max_seconds_left=300,
            fast_window_seconds=60,
            slow_window_seconds=600,
        )
        self.client = client or ProductionClient(max_order_cost=MAXIMUM_ALL_IN)
        self.journal = Journal(self.root / "orders.sqlite3", max_order_cost=MAXIMUM_ALL_IN)
        identity = hashlib.sha256(self.client.key_id.encode()).hexdigest()
        self.journal.register(self.cfg.to_dict(), identity, STRATEGY, CONFIG_REVISION)
        frozen = registration()
        self.journal.register_risk_policy(frozen["risk"])
        self.journal.register_hold_policy(frozen["position"])
        self.status = {
            "environment": "production",
            "real_money": True,
            "strategy": STRATEGY,
            "runner_revision": RUNNER_NAME,
            "state": "starting",
            "required_initial_cash": str(STARTING_CASH),
            "funding_revision": FUNDING_REVISION,
            "risk_per_market": str(MAXIMUM_ALL_IN),
            "risk_policy_revision": RISK_REVISION,
            "config_revision": CONFIG_REVISION,
            "position_policy_revision": HOLD_REVISION,
            "candidate_registration_sha256": registration_hash(),
            "source_study": "023",
            "source_risk_study": "027",
            "exchange_index": 2,
            "subaccount": 0,
            "execution": "completed-minute decision; 500ms delayed IOC; one attempt; no POST retry",
            "strategy_parameters": frozen,
            "started_ns": time.time_ns(),
        }
        self.account_at = 0.0
        self.settlement_at = 0.0
        self.counterfactual_at = 0.0
        self.last_evaluated_boundary = {}
        self.rejections = {}
        self.kelly_cap_binding_signals = 0

    def reject(self, reason):
        self.rejections[reason] = self.rejections.get(reason, 0) + 1
        return None

    def signal(self, ticker, cash, now_ns=None):
        now_ns = now_ns or time.time_ns()
        meta = self.state_provider().metadata(ticker)
        if not meta:
            return None
        boundary = minute_boundary(now_ns, meta[2])
        if boundary is None or self.last_evaluated_boundary.get(ticker) == boundary:
            return None
        self.last_evaluated_boundary[ticker] = boundary
        if self.journal.attempts(ticker) or self.journal.entry_position(ticker):
            return self.reject("market_already_attempted")
        state = self.state_provider()
        market = state.markets.get(ticker, {})
        if market.get("status") != "active" or market.get("result"):
            return self.reject("market_unavailable")
        if not state.fee_supported(self.cfg, ticker, now_ns):
            return self.reject("missing_or_unsupported_series_fees")
        book = state.books.get(ticker)
        if (
            not book
            or not book.valid
            or now_ns - book.at_ns > self.cfg.max_book_age_ms * 1_000_000
        ):
            return self.reject("stale_or_invalid_book")
        raw = forecast_at_completed_minute(state, ticker, boundary, now_ns, self.cfg)
        if raw is None:
            return self.reject("missing_or_stale_forecast_inputs")
        yes_ask, no_ask = book.best_ask("yes"), book.best_ask("no")
        if yes_ask is None or no_ask is None:
            return self.reject("missing_two_sided_quote")
        market_yes = float((yes_ask + Decimal(1) - no_ask) / 2)
        pooled_yes = blend_probability(
            raw["yes_probability"], market_yes, MARKET_LOG_ODDS_WEIGHT
        )
        candidates = []
        for side, price, probability in (
            ("yes", yes_ask, pooled_yes),
            ("no", no_ask, 1 - pooled_yes),
        ):
            edge = probability - float(price + entry_fee(price, 1, self.cfg))
            candidates.append((edge, side, price, probability))
        edge, side, price, probability = max(
            candidates, key=lambda value: (value[0], value[1] == "yes")
        )
        spread = yes_ask + no_ask - Decimal(1)
        if edge < MINIMUM_NET_EDGE:
            return self.reject("minimum_net_edge")
        if not MINIMUM_SELECTED_ASK <= price < MAXIMUM_SELECTED_ASK:
            return self.reject("selected_ask_band")
        if abs(raw["yes_probability"] - market_yes) > MAXIMUM_MODEL_MARKET_GAP:
            return self.reject("raw_model_market_gap")
        if spread > MAXIMUM_BINARY_SPREAD:
            return self.reject("binary_spread")
        stressed_price = price + ADVERSE_PRICE_BUFFER
        stressed_edge = probability - float(
            stressed_price + entry_fee(stressed_price, 1, self.cfg)
        )
        if stressed_price >= 1 or stressed_edge < 0:
            return self.reject("minimum_two_cent_stressed_edge")
        target, full_kelly = half_kelly_target(probability, price, cash, self.cfg)
        quantity = quantity_for_budget(price, target, self.cfg)
        if quantity < 1:
            return self.reject("kelly_budget_below_one_contract")
        if target == MAXIMUM_ALL_IN:
            self.kelly_cap_binding_signals += 1
        reservation = price * quantity + entry_fee(price, quantity, self.cfg)
        decision = {
            "ticker": ticker,
            "side": side,
            "limit": price,
            "quantity": quantity,
            "created_ns": now_ns,
            "arrival_ns": now_ns + self.cfg.latency_ms * 1_000_000,
            "reservation": reservation,
            "target_budget": target,
            "full_kelly_fraction": full_kelly,
            "kelly_multiplier": KELLY_MULTIPLIER,
            "probability": probability,
            "edge": edge,
            "stressed_edge": stressed_edge,
            "raw_model_probability": raw["yes_probability"],
            "market_yes_probability": market_yes,
            "pooled_yes_probability": pooled_yes,
            "binary_spread": spread,
            "forecast": raw,
            "decision_boundary_second": boundary,
        }
        self.status["last_signal"] = decision
        return decision

    async def step(self):
        await self.settlements()
        if not await self.reconcile():
            self.status["state"] = "blocked_unconfirmed_order"
            return
        positions_data = await self.read(
            "/portfolio/positions", {"exchange_index": 2, "limit": 1000}
        )
        if positions_data.get("cursor"):
            raise RuntimeError("Production account exposure pagination was not exhausted")
        if await self.manage_position(positions_data.get("market_positions", [])):
            return
        cash = await self.account()
        commissioned = valid_commission_receipt(self.root)
        self.status["commissioned"] = commissioned
        if (self.root / ENTRY_PAUSE_FILE).exists():
            self.status.update(state="entries_paused", markets=self.current_markets())
            return
        if not self.journal.rows() and not commissioned and cash != STARTING_CASH:
            self.status.update(state="waiting_initial_production_funding", markets=self.current_markets())
            return
        markets = self.current_markets()
        self.status.update(state="watching", markets=markets)
        for ticker in markets:
            decision = self.signal(ticker, cash)
            if decision is None:
                continue
            attempt_id = "signal-" + uuid.uuid4().hex
            self.journal.begin_attempt(attempt_id, decision)
            if not await self.exchange_ready():
                self.status["state"] = "exchange_paused"
                self.journal.finish_attempt(attempt_id, "arrival_canceled")
                return
            clear, positions, resting = await self.exposure_clear()
            if not clear:
                self.status.update(
                    state="existing_account_exposure",
                    nonzero_position_count=len(positions),
                    resting_order_count=len(resting),
                )
                self.journal.finish_attempt(attempt_id, "arrival_canceled")
                return
            cash = await self.account()
            if cash < Decimal(decision["reservation"]):
                self.status["state"] = "insufficient_production_cash"
                self.journal.finish_attempt(attempt_id, "arrival_canceled")
                return
            delay = (int(decision["arrival_ns"]) - time.time_ns()) / 1e9
            if delay > 0:
                await asyncio.sleep(delay)
            preview = self.arrival_fill_preview(decision)
            if preview is None:
                self.status["state"] = "arrival_ioc_not_marketable"
                self.journal.finish_attempt(attempt_id, "arrival_canceled")
                return
            payload = order_payload({**decision, "quantity": preview["quantity"]})
            if payload is None:
                self.journal.finish_attempt(attempt_id, "arrival_canceled")
                return
            self.journal.intent(payload, decision, attempt_id=attempt_id)
            started_ns = time.time_ns()
            try:
                response = await self.client.submit(payload)
                self.status["last_order_ack"] = {
                    "client_order_id": payload["client_order_id"],
                    "ticker": ticker,
                    "received": bool(response),
                    "elapsed_ms": (time.time_ns() - started_ns) / 1e6,
                }
            except httpx.HTTPStatusError as exc:
                definitive = exc.response.status_code in (400, 401, 403, 422, 429)
                self.journal.error(
                    payload["client_order_id"],
                    "HTTP_" + str(exc.response.status_code),
                    definitive=definitive,
                )
                if exc.response.status_code in (401, 403):
                    raise RuntimeError("Production credential lacks order permission") from None
            except httpx.RequestError as exc:
                self.journal.error(payload["client_order_id"], type(exc).__name__)
            await self.reconcile()
            return

    def snapshot(self):
        rows = self.journal.rows()
        orders = [json.loads(row["exchange_order"]) for row in rows if row["exchange_order"]]
        settled = self.journal.settled()
        attempts = self.journal.recorded_attempts()
        self.status.update(
            updated_ns=time.time_ns(),
            entries_paused=(self.root / ENTRY_PAUSE_FILE).exists(),
            stop_exists=(self.root / "STOP").exists(),
            submitted_attempts=len(rows),
            recorded_signal_attempts=len(attempts),
            arrival_cancellations=sum(row["state"] == "arrival_canceled" for row in attempts),
            settled_markets=len(settled),
            realized_net_pnl=str(sum((Decimal(row["pnl"]) for row in settled), Decimal(0))),
            filled_markets=sum(fill_count(order) > 0 for order in orders),
            unresolved_orders=len(self.journal.pending()),
            kelly_cap_binding_signals=self.kelly_cap_binding_signals,
            rejections=dict(sorted(self.rejections.items())),
            recent_orders=[
                {
                    "ticker": row["ticker"],
                    "state": row["state"],
                    "error": row["error"],
                    "order": json.loads(row["exchange_order"]) if row["exchange_order"] else None,
                }
                for row in rows[-10:]
            ],
        )
        temp = self.root / "status.tmp"
        temp.write_text(dumps(self.status))
        os.replace(temp, self.root / "status.json")
