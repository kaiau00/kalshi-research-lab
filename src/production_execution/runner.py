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

from research_lab.engine import Replay, entry_fee
from research_lab.settings import Experiment

from .client import ProductionClient
from .journal import Journal, dumps, fill_count

STRATEGY = "adaptive_volatility"
STARTING_CASH = Decimal("100.00")
RISK_PER_MARKET = Decimal("3.00")
CONFIG_REVISION = "adaptive-production-001-20261007"
AUTHORIZATION = "real-btc-15m-adaptive-3usd-2026-10-07"
EXIT_AUTHORIZATION = "real-btc-15m-adaptive-monitored-exit-2026-10-07"
EXIT_REVISION = "adaptive-monitored-exit-001-20261007"
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
        if os.environ.get("LAB_PRODUCTION_AUTHORIZATION") != AUTHORIZATION:
            raise RuntimeError("Production execution authorization token is absent")
        if os.environ.get("LAB_PRODUCTION_EXIT_AUTHORIZATION") != EXIT_AUTHORIZATION:
            raise RuntimeError("Production monitored-exit authorization token is absent")
        if state_provider is None:
            raise ValueError("Production market-state provider is required")
        self.state_provider = state_provider
        self.root = Path(root or os.environ.get("LAB_PRODUCTION_DIR", "/data/production-adaptive-001"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = (self.root / "runner.lock").open("a")
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.cfg = Experiment(bankroll=str(STARTING_CASH), risk_per_market=str(RISK_PER_MARKET))
        self.client = client or ProductionClient(max_order_cost=RISK_PER_MARKET)
        self.journal = Journal(self.root / "orders.sqlite3", max_order_cost=RISK_PER_MARKET)
        identity = hashlib.sha256(self.client.key_id.encode()).hexdigest()
        self.journal.register(self.cfg.to_dict(), identity, STRATEGY, CONFIG_REVISION)
        self.journal.register_exit(
            {
                "revision": EXIT_REVISION,
                "monitor_interval_seconds": 1,
                "take_profit_per_contract": str(TAKE_PROFIT_PER_CONTRACT),
                "exit_value_margin": str(EXIT_VALUE_MARGIN),
                "thesis_invalidation": "probability_at_or_below_entry_all_in_basis",
                "execution": "reduce-only IOC against displayed best bid",
                "maximum_exit_attempts_per_market": 3,
            }
        )
        self.status = {
            "environment": "production",
            "real_money": True,
            "strategy": STRATEGY,
            "state": "starting",
            "bankroll_baseline": str(STARTING_CASH),
            "risk_per_market": str(RISK_PER_MARKET),
            "config_revision": CONFIG_REVISION,
            "exchange_index": 2,
            "subaccount": 0,
            "execution": "500ms delayed entry IOC; 1s monitored reduce-only exit IOC; no POST retry",
            "exit_revision": EXIT_REVISION,
            "strategy_parameters": {
                "min_seconds_left": self.cfg.min_seconds_left,
                "max_seconds_left": self.cfg.max_seconds_left,
                "min_net_edge": self.cfg.min_edge,
                "fast_window_seconds": self.cfg.fast_window_seconds,
                "slow_window_seconds": self.cfg.slow_window_seconds,
                "variance_blend": "70% fast + 30% slow",
                "sizing": "fixed",
                "take_profit_per_contract": str(TAKE_PROFIT_PER_CONTRACT),
                "exit_value_margin": str(EXIT_VALUE_MARGIN),
                "thesis_invalidation": "probability_at_or_below_entry_all_in_basis",
            },
            "started_ns": time.time_ns(),
        }
        self.account_at = 0.0
        self.settlement_at = 0.0

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
        model = Replay(self.cfg)
        model.state = self.state_provider()
        account = model.accounts[STRATEGY]
        account.cash = min(STARTING_CASH, cash)
        attempts = self.journal.attempts(ticker)
        account.attempts[ticker] = len(attempts)
        if attempts:
            account.last_attempt[ticker] = attempts[-1]["created_ns"]
        if self.journal.entry_position(ticker):
            account.traded.add(ticker)
        model._decide(account, ticker, now_ns or time.time_ns())
        self.status["last_rejections"] = account.rejected
        return account.pending.get(ticker)

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
            state="monitoring_position",
            open_position={
                "ticker": ticker,
                "side": position["side"],
                "quantity": str(position["remaining"]),
                "basis_per_contract": str(position["basis_per_contract"]),
            },
        )
        decision = self.exit_decision(position)
        if decision is None:
            return True
        if not await self.exchange_ready():
            self.status["state"] = "exchange_paused_with_position"
            return True
        payload = exit_payload(
            ticker,
            position["side"],
            decision["quantity"],
            decision["outcome_bid"],
        )
        if payload is None:
            return True
        self.journal.exit_intent(payload, decision)
        started_ns = time.time_ns()
        try:
            response = await self.client.submit(payload)
            self.status["last_exit_ack"] = {
                "client_order_id": payload["client_order_id"],
                "ticker": ticker,
                "received": bool(response),
                "elapsed_ms": (time.time_ns() - started_ns) / 1e6,
                "triggers": decision["triggers"],
            }
        except httpx.HTTPStatusError as exc:
            definitive = exc.response.status_code in (400, 401, 403, 422, 429)
            self.journal.error(
                payload["client_order_id"],
                "HTTP_" + str(exc.response.status_code),
                definitive=definitive,
            )
            if exc.response.status_code in (401, 403):
                raise RuntimeError("Production credential lacks exit-order permission") from None
        except httpx.RequestError as exc:
            self.journal.error(payload["client_order_id"], type(exc).__name__)
        await self.reconcile()
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
            state = self.state_provider()
            book = state.books.get(ticker)
            meta = state.metadata(ticker)
            levels = book.asks(decision["side"]) if book and book.valid else []
            if (
                not meta
                or time.time_ns() >= meta[2]
                or not levels
                or time.time_ns() - book.at_ns > self.cfg.max_book_age_ms * 1_000_000
                or levels[0][0] > Decimal(decision["limit"])
            ):
                self.status["state"] = "arrival_ioc_not_marketable"
                self.journal.finish_attempt(attempt_id, "arrival_canceled")
                continue
            payload = order_payload(decision)
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
        self.status.update(
            updated_ns=time.time_ns(),
            submitted_attempts=len(rows),
            recorded_signal_attempts=len(attempts),
            arrival_cancellations=sum(row["state"] == "arrival_canceled" for row in attempts),
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
