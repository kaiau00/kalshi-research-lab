from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import time
import uuid
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

import httpx

from market_anchor_study.report import (
    CANDIDATE,
    MAX_BINARY_SPREAD,
    MAX_DECISION_PRICE,
    MAX_MODEL_MARKET_GAP,
    MIN_DECISION_PRICE,
    qualifies,
    registration_hash,
)
from research_lab.engine import Replay, entry_fee
from research_lab.settings import Experiment

from .client import ProductionClient
from .journal import Journal, dumps, fill_count

STRATEGY = CANDIDATE
SOURCE_STRATEGY = "adaptive_volatility"
STARTING_CASH = Decimal("57.9544")
RISK_PER_MARKET = Decimal("1.00")
CONFIG_REVISION = "market-anchor-production-001-20261009"
AUTHORIZATION = "real-btc-15m-market-anchor-001-2026-10-09"
RISK_AUTHORIZATION = "real-btc-15m-market-anchor-1usd-2026-10-09"
RISK_REVISION = "market-anchor-fixed-risk-001-20261009"
HOLD_AUTHORIZATION = "real-btc-15m-market-anchor-hold-2026-10-09"
HOLD_REVISION = "market-anchor-hold-settlement-001-20261009"
ENTRY_PAUSE_FILE = "PAUSE_ENTRIES"
TAKE_PROFIT_PER_CONTRACT = Decimal("0.05")
EXIT_VALUE_MARGIN = Decimal("0.02")


def order_payload(decision):
    price = Decimal(decision["limit"])
    quantity = int(decision["quantity"])
    unit = (price + entry_fee(price, 1, Experiment())).quantize(Decimal(".01"), rounding=ROUND_CEILING)
    quantity = min(quantity, int(RISK_PER_MARKET / unit))
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


def exit_payload(ticker, held_side, count, outcome_bid):
    if held_side not in ("yes", "no"):
        raise ValueError("Invalid held outcome side")
    count = int(count)
    outcome_bid = Decimal(outcome_bid)
    if count < 1 or not outcome_bid.is_finite() or not 0 < outcome_bid < 1:
        return None
    return {
        "ticker": ticker,
        "client_order_id": "prod-" + uuid.uuid4().hex,
        # V2 orders use one YES-price book. Selling YES is an ask; selling NO is
        # the equivalent reduce-only YES bid at 1 - the executable NO bid.
        "side": "ask" if held_side == "yes" else "bid",
        "price": str(outcome_bid if held_side == "yes" else 1 - outcome_bid),
        "count": str(count),
        "time_in_force": "immediate_or_cancel",
        "self_trade_prevention_type": "taker_at_cross",
        "reduce_only": True,
        "exchange_index": 2,
        "subaccount": 0,
    }


class Runner:
    def __init__(self, state_provider, root=None, client=None):
        if os.environ.get("LAB_MARKET_ANCHOR_PRODUCTION_AUTHORIZATION") != AUTHORIZATION:
            raise RuntimeError("Market Anchor production authorization token is absent")
        if os.environ.get("LAB_MARKET_ANCHOR_RISK_AUTHORIZATION") != RISK_AUTHORIZATION:
            raise RuntimeError("Market Anchor one-dollar risk authorization token is absent")
        if os.environ.get("LAB_MARKET_ANCHOR_HOLD_AUTHORIZATION") != HOLD_AUTHORIZATION:
            raise RuntimeError("Market Anchor hold-to-settlement authorization token is absent")
        if state_provider is None:
            raise ValueError("Production market-state provider is required")
        self.state_provider = state_provider
        self.root = Path(
            root
            or os.environ.get(
                "LAB_MARKET_ANCHOR_PRODUCTION_DIR", "/data/production-market-anchor-001"
            )
        )
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = (self.root / "runner.lock").open("a")
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.cfg = Experiment(bankroll=str(STARTING_CASH), risk_per_market=str(RISK_PER_MARKET))
        self.client = client or ProductionClient(max_order_cost=RISK_PER_MARKET)
        self.journal = Journal(self.root / "orders.sqlite3", max_order_cost=RISK_PER_MARKET)
        identity = hashlib.sha256(self.client.key_id.encode()).hexdigest()
        self.journal.register(self.cfg.to_dict(), identity, STRATEGY, CONFIG_REVISION)
        self.journal.register_risk_policy(
            {
                "revision": RISK_REVISION,
                "maximum_all_in_entry_cost": str(RISK_PER_MARKET),
                "sizing": "fixed",
                "effective_scope": "all entries in this production revision",
            }
        )
        self.journal.register_hold_policy(
            {
                "revision": HOLD_REVISION,
                "position_policy": "hold_to_official_settlement",
                "monitor": "verify exact signed exchange position against durable ledger",
                "early_exit_submission": "disabled",
            }
        )
        self.status = {
            "environment": "production",
            "real_money": True,
            "strategy": STRATEGY,
            "state": "starting",
            "bankroll_baseline": str(STARTING_CASH),
            "risk_per_market": str(RISK_PER_MARKET),
            "risk_policy_revision": RISK_REVISION,
            "config_revision": CONFIG_REVISION,
            "candidate_registration_sha256": registration_hash(),
            "exchange_index": 2,
            "subaccount": 0,
            "execution": "500ms delayed entry IOC; hold to official settlement; no POST retry",
            "position_policy_revision": HOLD_REVISION,
            "strategy_parameters": {
                "min_seconds_left": self.cfg.min_seconds_left,
                "max_seconds_left": self.cfg.max_seconds_left,
                "min_net_edge": self.cfg.min_edge,
                "fast_window_seconds": self.cfg.fast_window_seconds,
                "slow_window_seconds": self.cfg.slow_window_seconds,
                "variance_blend": "70% fast + 30% slow",
                "minimum_selected_side_ask": str(MIN_DECISION_PRICE),
                "maximum_selected_side_ask_exclusive": str(MAX_DECISION_PRICE),
                "maximum_absolute_raw_vs_market_yes_probability_gap": MAX_MODEL_MARKET_GAP,
                "maximum_binary_spread": str(MAX_BINARY_SPREAD),
                "sizing": "fixed",
                "maximum_all_in_entry_cost": str(RISK_PER_MARKET),
                "position_management": "hold_to_official_settlement",
                "early_exit_submission": "disabled",
            },
            "started_ns": time.time_ns(),
        }
        self.account_at = 0.0
        self.settlement_at = 0.0
        self.counterfactual_at = 0.0

    async def read(self, path, params=None):
        return await self.client.get(path, params)

    def current_markets(self):
        now_ns = time.time_ns()
        state = self.state_provider()
        current = []
        for ticker, market in state.markets.items():
            meta = state.metadata(ticker)
            if (
                meta
                and market.get("status") == "active"
                and market.get("exchange_index") == 2
                and 0 < meta[2] - now_ns <= 1_800_000_000_000
            ):
                current.append(ticker)
        return sorted(current)

    def signal(self, ticker, cash, now_ns=None):
        now_ns = now_ns or time.time_ns()
        model = Replay(self.cfg)
        model.state = self.state_provider()
        account = model.accounts[SOURCE_STRATEGY]
        account.cash = min(STARTING_CASH, cash)
        attempts = self.journal.attempts(ticker)
        account.attempts[ticker] = len(attempts)
        if attempts:
            account.last_attempt[ticker] = attempts[-1]["created_ns"]
        if self.journal.entry_position(ticker) or any(
            row["state"] == "filter_rejected_marketable" for row in attempts
        ):
            account.traded.add(ticker)
        model._decide(account, ticker, now_ns)
        self.status["last_rejections"] = account.rejected
        decision = account.pending.get(ticker)
        if decision is None:
            return None
        book = model._fresh_book(ticker, now_ns)
        yes_ask = book.best_ask("yes") if book else None
        no_ask = book.best_ask("no") if book else None
        if yes_ask is None or no_ask is None:
            return None
        decision.update(
            raw_model_probability=decision["forecast"]["yes_probability"],
            market_yes_probability=float((yes_ask + Decimal(1) - no_ask) / 2),
            probability_transform="unchanged_adaptive",
            quoted_binary_spread=yes_ask + no_ask - Decimal(1),
        )
        accepted = qualifies(decision)
        decision["market_anchor_accepted"] = accepted
        self.status["last_market_anchor_evaluation"] = {
            "ticker": ticker,
            "accepted": accepted,
            "selected_side": decision["side"],
            "selected_side_ask": str(decision["limit"]),
            "raw_model_yes_probability": decision["raw_model_probability"],
            "market_yes_probability": decision["market_yes_probability"],
            "absolute_model_market_gap": abs(
                decision["raw_model_probability"] - decision["market_yes_probability"]
            ),
            "binary_spread": str(decision["quoted_binary_spread"]),
            "created_ns": decision["created_ns"],
        }
        if not accepted:
            self.status["market_anchor_filter_rejections"] = (
                self.status.get("market_anchor_filter_rejections", 0) + 1
            )
        return decision

    def arrival_fill_preview(self, decision, now_ns=None):
        now_ns = now_ns or time.time_ns()
        state = self.state_provider()
        book = state.books.get(decision["ticker"])
        meta = state.metadata(decision["ticker"])
        market = state.markets.get(decision["ticker"], {})
        levels = book.asks(decision["side"]) if book and book.valid else []
        if (
            not meta
            or now_ns >= meta[2]
            or market.get("status") != "active"
            or market.get("result")
            or not state.fee_supported(self.cfg, decision["ticker"], now_ns)
            or not levels
            or now_ns - book.at_ns > self.cfg.max_book_age_ms * 1_000_000
            or levels[0][0] > Decimal(decision["limit"])
        ):
            return None
        price, displayed = levels[0]
        quantity = min(int(decision["quantity"]), int(displayed))
        if quantity < 1:
            return None
        cost = price * quantity + entry_fee(price, quantity, self.cfg)
        if cost > Decimal(decision["reservation"]):
            return None
        return {"price": price, "quantity": quantity, "displayed_depth": displayed, "cost": cost}

    async def reconcile(self):
        pending = [("entry", row) for row in self.journal.pending()]
        pending += [("exit", row) for row in self.journal.pending_exits()]
        for kind, row in pending:
            cursor = ""
            found = None
            for _ in range(10):
                data = await self.read(
                    "/portfolio/orders",
                    {"ticker": row["ticker"], "exchange_index": 2, "limit": 200, "cursor": cursor},
                )
                matches = [order for order in data["orders"] if order["client_order_id"] == row["client_id"]]
                if matches:
                    if len(matches) != 1:
                        raise RuntimeError("Duplicate production client order ID")
                    found = matches[0]
                    break
                cursor = data.get("cursor", "")
                if not cursor:
                    break
            if found:
                if kind == "entry":
                    self.journal.reconcile(row["client_id"], found)
                else:
                    self.journal.reconcile_exit(row["client_id"], found)
        return not self.journal.pending() and not self.journal.pending_exits()

    @staticmethod
    def _outcome_bid(book, side):
        levels = book.yes if side == "yes" else book.no
        available = [(price, count) for price, count in levels.items() if count > 0]
        return max(available) if available else (None, Decimal(0))

    def exit_decision(self, position, now_ns=None):
        now_ns = now_ns or time.time_ns()
        ticker, side = position["ticker"], position["side"]
        state = self.state_provider()
        book = state.books.get(ticker)
        meta = state.metadata(ticker)
        if (
            not meta
            or now_ns >= meta[2]
            or not book
            or not book.valid
            or now_ns - book.at_ns > self.cfg.max_book_age_ms * 1_000_000
        ):
            return None
        outcome_bid, displayed = self._outcome_bid(book, side)
        if outcome_bid is None:
            return None
        quantity = min(int(position["remaining"]), int(displayed))
        if quantity < 1:
            return None
        fair = state.forecast(ticker, now_ns, self.cfg, adaptive=True)
        if fair is None:
            return None
        probability = Decimal(str(
            fair["yes_probability"] if side == "yes" else 1 - fair["yes_probability"]
        ))
        fee = entry_fee(outcome_bid, quantity, self.cfg)
        net_proceeds = outcome_bid * quantity - fee
        basis = position["basis_per_contract"] * quantity
        net_per_contract = net_proceeds / quantity
        triggers = []
        if net_proceeds - basis >= TAKE_PROFIT_PER_CONTRACT * quantity:
            triggers.append("take_profit")
        if net_per_contract >= probability + EXIT_VALUE_MARGIN:
            triggers.append("exit_value_above_model")
        if probability <= position["basis_per_contract"]:
            triggers.append("entry_thesis_invalidated")
        if not triggers:
            return None
        return {
            "ticker": ticker,
            "held_side": side,
            "quantity": quantity,
            "outcome_bid": outcome_bid,
            "displayed_depth": displayed,
            "entry_basis_per_contract": position["basis_per_contract"],
            "modeled_probability": probability,
            "estimated_exit_fee": fee,
            "estimated_net_proceeds": net_proceeds,
            "estimated_exit_pnl": net_proceeds - basis,
            "triggers": triggers,
            "forecast": fair,
            "created_ns": now_ns,
        }

    async def manage_position(self, positions):
        tracked = self.journal.open_positions()
        nonzero = {
            item["ticker"]: item
            for item in positions
            if Decimal(str(item.get("position_fp", "0"))) != 0
        }
        if set(nonzero) != set(tracked):
            self.status.update(
                state="existing_account_exposure",
                nonzero_position_count=len(nonzero),
                tracked_position_count=len(tracked),
            )
            return bool(nonzero or tracked)
        if not tracked:
            self.status.pop("open_position", None)
            return False
        if len(tracked) != 1:
            raise RuntimeError("Production ledger contains multiple open positions")
        ticker, position = next(iter(tracked.items()))
        exchange_quantity = Decimal(str(nonzero[ticker]["position_fp"]))
        expected = position["remaining"] if position["side"] == "yes" else -position["remaining"]
        if exchange_quantity != expected:
            raise RuntimeError("Production account position differs from durable ledger")
        self.status.update(
            state="holding_to_settlement",
            open_position={
                "ticker": ticker,
                "side": position["side"],
                "quantity": str(position["remaining"]),
                "basis_per_contract": str(position["basis_per_contract"]),
            },
        )
        return True

    async def account(self):
        balance = await self.read("/portfolio/balance", {"exchange_index": 2})
        cash = Decimal(str(balance["balance_dollars"]))
        if not cash.is_finite() or cash < 0:
            raise RuntimeError("Invalid production balance")
        self.status.update(
            cash=str(cash),
            portfolio_value_cents=balance.get("portfolio_value"),
            balance_observed_ns=time.time_ns(),
        )
        return cash

    async def settlements(self):
        if time.time() - self.settlement_at < 30:
            return
        done = {row["ticker"] for row in self.journal.settled()}
        for row in self.journal.rows():
            ticker = row["ticker"]
            if ticker in done or not row["exchange_order"]:
                continue
            if fill_count(json.loads(row["exchange_order"])) <= 0:
                continue
            position = self.journal.entry_position(ticker)
            if not position or position["remaining"] <= 0:
                continue
            data = await self.read("/portfolio/settlements", {"ticker": ticker, "limit": 100})
            if data.get("cursor"):
                raise RuntimeError("Unexpected production settlement pagination")
            matches = [
                item
                for item in data["settlements"]
                if item["ticker"] == ticker and item["exchange_index"] == 2
            ]
            if len(matches) > 1:
                raise RuntimeError("Multiple production settlements for one ticker")
            if matches:
                self.journal.settlement(ticker, matches[0])
        self.settlement_at = time.time()

    async def update_counterfactuals(self):
        if time.time() - self.counterfactual_at < 30:
            return
        state = self.state_provider()
        done = self.journal.counterfactual_tickers()
        for ticker in self.journal.exited_tickers() - done:
            market = state.markets.get(ticker, {})
            if market.get("status") != "finalized" or market.get("result") not in ("yes", "no"):
                try:
                    try:
                        response = await self.read("/markets/" + ticker)
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code != 404:
                            raise
                        response = await self.read("/historical/markets/" + ticker)
                    market = response.get("market", response)
                    if market.get("ticker") != ticker:
                        raise RuntimeError("Counterfactual market response changed ticker")
                except (httpx.HTTPError, RuntimeError, KeyError) as exc:
                    self.status["exit_counterfactual_error"] = type(exc).__name__
                    continue
            if market.get("status") != "finalized" or market.get("result") not in ("yes", "no"):
                continue
            self.journal.record_counterfactual(ticker, market["result"])
            self.status.pop("exit_counterfactual_error", None)
        self.counterfactual_at = time.time()

    async def exposure_clear(self):
        positions = await self.read("/portfolio/positions", {"exchange_index": 2, "limit": 1000})
        orders = await self.read(
            "/portfolio/orders", {"exchange_index": 2, "status": "resting", "limit": 200}
        )
        if positions.get("cursor") or orders.get("cursor"):
            raise RuntimeError("Production account exposure pagination was not exhausted")
        nonzero = [
            item
            for item in positions.get("market_positions", [])
            if Decimal(str(item.get("position_fp", "0"))) != 0
        ]
        return not nonzero and not orders.get("orders"), nonzero, orders.get("orders", [])

    async def exchange_ready(self):
        data = await self.read("/exchange/status")
        shards = [item for item in data.get("exchange_index_statuses", []) if item["exchange_index"] == 2]
        return bool(
            data.get("trading_active")
            and data.get("exchange_active")
            and len(shards) == 1
            and shards[0].get("trading_active")
            and shards[0].get("exchange_active")
        )

    async def step(self):
        await self.settlements()
        if not await self.reconcile():
            self.status["state"] = "blocked_unconfirmed_order"
            return
        await self.update_counterfactuals()
        positions_data = await self.read(
            "/portfolio/positions", {"exchange_index": 2, "limit": 1000}
        )
        if positions_data.get("cursor"):
            raise RuntimeError("Production account exposure pagination was not exhausted")
        if await self.manage_position(positions_data.get("market_positions", [])):
            return
        cash = await self.account()
        if not self.journal.rows() and cash != STARTING_CASH:
            self.status["state"] = "waiting_initial_production_funding"
            return
        if (self.root / ENTRY_PAUSE_FILE).exists():
            self.status.update(state="entries_paused", markets=self.current_markets())
            return
        markets = self.current_markets()
        self.status.update(state="watching", markets=markets)
        for ticker in markets:
            decision = self.signal(ticker, cash)
            if decision is None:
                continue
            attempt_id = "signal-" + uuid.uuid4().hex
            self.journal.begin_attempt(attempt_id, decision)
            if not decision["market_anchor_accepted"]:
                delay = (int(decision["arrival_ns"]) - time.time_ns()) / 1e9
                if delay > 0:
                    await asyncio.sleep(delay)
                if self.arrival_fill_preview(decision) is None:
                    self.status["state"] = "arrival_ioc_not_marketable"
                    self.journal.finish_attempt(attempt_id, "arrival_canceled")
                else:
                    self.status["state"] = "market_anchor_filtered_out"
                    self.journal.finish_attempt(attempt_id, "filter_rejected_marketable")
                continue
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
                continue
            payload = order_payload({**decision, "quantity": preview["quantity"]})
            if payload is None:
                self.journal.finish_attempt(attempt_id, "arrival_canceled")
                continue
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

    def snapshot(self):
        rows = self.journal.rows()
        orders = [json.loads(row["exchange_order"]) for row in rows if row["exchange_order"]]
        settled = self.journal.settled()
        exits = self.journal.exit_rows()
        attempts = self.journal.recorded_attempts()
        counterfactuals = self.journal.counterfactuals()
        counterfactual_actual = sum(
            (Decimal(row["actual_pnl"]) for row in counterfactuals), Decimal(0)
        )
        counterfactual_hold = sum(
            (Decimal(row["hold_pnl"]) for row in counterfactuals), Decimal(0)
        )
        counterfactual_advantage = counterfactual_actual - counterfactual_hold
        self.status.update(
            updated_ns=time.time_ns(),
            entries_paused=(self.root / ENTRY_PAUSE_FILE).exists(),
            stop_exists=(self.root / "STOP").exists(),
            submitted_attempts=len(rows),
            recorded_signal_attempts=len(attempts),
            arrival_cancellations=sum(row["state"] == "arrival_canceled" for row in attempts),
            market_anchor_filtered_marketable=sum(
                row["state"] == "filter_rejected_marketable" for row in attempts
            ),
            settled_markets=len(settled),
            realized_net_pnl=str(
                sum((Decimal(row["pnl"]) for row in settled), Decimal(0))
                + self.journal.exit_pnl()
            ),
            filled_markets=sum(fill_count(order) > 0 for order in orders),
            exit_attempts=len(exits),
            exit_fills=sum(
                fill_count(json.loads(row["exchange_order"])) > 0
                for row in exits
                if row["exchange_order"]
            ),
            early_exit_net_pnl=str(self.journal.exit_pnl()),
            exit_counterfactual={
                "officially_resolved": len(counterfactuals),
                "pending_official_results": len(
                    self.journal.exited_tickers() - self.journal.counterfactual_tickers()
                ),
                "actual_net_pnl": str(counterfactual_actual),
                "hold_to_settlement_net_pnl": str(counterfactual_hold),
                "exit_advantage": str(counterfactual_advantage),
                "exits_helped": sum(Decimal(row["exit_advantage"]) > 0 for row in counterfactuals),
                "exits_hurt": sum(Decimal(row["exit_advantage"]) < 0 for row in counterfactuals),
                "ties": sum(Decimal(row["exit_advantage"]) == 0 for row in counterfactuals),
                "recent": [
                    {
                        **json.loads(row["details"]),
                        "finalized_ns": row["finalized_ns"],
                    }
                    for row in counterfactuals[-10:]
                ],
            },
            unresolved_orders=len(self.journal.pending()) + len(self.journal.pending_exits()),
            recent_orders=[
                {
                    "ticker": row["ticker"],
                    "state": row["state"],
                    "error": row["error"],
                    "order": json.loads(row["exchange_order"]) if row["exchange_order"] else None,
                }
                for row in rows[-10:]
            ],
            recent_exits=[
                {
                    "ticker": row["ticker"],
                    "state": row["state"],
                    "error": row["error"],
                    "trigger": json.loads(row["trigger"]),
                    "order": json.loads(row["exchange_order"]) if row["exchange_order"] else None,
                    "pnl": row["pnl"],
                }
                for row in exits[-10:]
            ],
        )
        temp = self.root / "status.tmp"
        temp.write_text(dumps(self.status))
        os.replace(temp, self.root / "status.json")

    async def run(self):
        try:
            while True:
                if (self.root / "STOP").exists():
                    self.status["state"] = "stopped_by_file"
                else:
                    try:
                        await self.step()
                        self.status.pop("error", None)
                    except (httpx.HTTPError, TimeoutError) as exc:
                        self.status.update(state="waiting_api", error=type(exc).__name__)
                self.snapshot()
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.status.update(state="stopped_error", error=f"{type(exc).__name__}: {exc}")
            self.snapshot()
            raise
        finally:
            await self.client.close()
            self.journal.db.close()
            self.lock.close()
