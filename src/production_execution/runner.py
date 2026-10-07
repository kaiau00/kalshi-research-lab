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


class Runner:
    def __init__(self, state_provider, root=None, client=None):
        if os.environ.get("LAB_PRODUCTION_AUTHORIZATION") != AUTHORIZATION:
            raise RuntimeError("Production execution authorization token is absent")
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
            "execution": "500ms delayed IOC; no resting order and no POST retry",
            "strategy_parameters": {
                "min_seconds_left": self.cfg.min_seconds_left,
                "max_seconds_left": self.cfg.max_seconds_left,
                "min_net_edge": self.cfg.min_edge,
                "fast_window_seconds": self.cfg.fast_window_seconds,
                "slow_window_seconds": self.cfg.slow_window_seconds,
                "variance_blend": "70% fast + 30% slow",
                "sizing": "fixed",
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
        rows = self.journal.rows(ticker)
        account.attempts[ticker] = len(rows)
        if rows:
            account.last_attempt[ticker] = rows[-1]["created_ns"]
        if any(row["exchange_order"] and fill_count(json.loads(row["exchange_order"])) > 0 for row in rows):
            account.traded.add(ticker)
        model._decide(account, ticker, now_ns or time.time_ns())
        self.status["last_rejections"] = account.rejected
        return account.pending.get(ticker)

    async def reconcile(self):
        for row in self.journal.pending():
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
                self.journal.reconcile(row["client_id"], found)
        return not self.journal.pending()

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
            if not await self.exchange_ready():
                self.status["state"] = "exchange_paused"
                return
            clear, positions, resting = await self.exposure_clear()
            if not clear:
                self.status.update(
                    state="existing_account_exposure",
                    nonzero_position_count=len(positions),
                    resting_order_count=len(resting),
                )
                return
            cash = await self.account()
            if cash < Decimal(decision["reservation"]):
                self.status["state"] = "insufficient_production_cash"
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
                continue
            payload = order_payload(decision)
            if payload is None:
                continue
            self.journal.intent(payload, decision)
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
        self.status.update(
            updated_ns=time.time_ns(),
            submitted_attempts=len(rows),
            settled_markets=len(settled),
            realized_net_pnl=str(sum((Decimal(row["pnl"]) for row in settled), Decimal(0))),
            filled_markets=sum(fill_count(order) > 0 for order in orders),
            unresolved_orders=len(self.journal.pending()),
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

