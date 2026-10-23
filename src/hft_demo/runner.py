"""Standalone, demo-only deterministic HFT runner for Study 029."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import time
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from research_lab.market import MarketState
from research_lab.settings import Experiment
from research_lab.storage import Event

from .client import WS, DemoHFTClient
from .engine import Config, Level, Snapshot, decide
from .journal import Journal, dumps
from .registration import AUTHORIZATION, CONFIG_REVISION, STRATEGY, registration, registration_hash

MAX_GROSS_PREMIUM = Decimal("5.00")
ALLOWED_STATES = {"resting", "canceled", "executed"}


def close_timestamp(market: dict) -> float | None:
    try:
        return datetime.fromisoformat(market["close_time"].replace("Z", "+00:00")).timestamp()
    except (KeyError, TypeError, ValueError):
        return None


def parse_top(data: dict, received_ns: int, ticker: str, probability: float, inventory: int) -> Snapshot:
    raw = data["orderbook_fp"]
    yes = [(Decimal(str(p)), Decimal(str(q))) for p, q in raw.get("yes_dollars", [])]
    no = [(Decimal(str(p)), Decimal(str(q))) for p, q in raw.get("no_dollars", [])]
    if not yes or not no:
        raise ValueError("two-sided demo book required")
    if any(not 0 < p < 1 or q <= 0 for p, q in yes + no):
        raise ValueError("invalid demo depth")
    yes_bid = max(yes)
    no_bid = max(no)
    yes_ask = (1 - no_bid[0], no_bid[1])
    if yes_bid[0] >= yes_ask[0]:
        raise ValueError("crossed demo book")
    return Snapshot(
        ticker=ticker,
        received_ns=received_ns,
        seconds_left=0,
        raw_yes_probability=probability,
        inventory=inventory,
        yes_bid=Level(*yes_bid),
        yes_ask=Level(*yes_ask),
    )


def make_payload(quote, *, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    return {
        "ticker": quote.ticker,
        "client_order_id": "hft-" + uuid.uuid4().hex,
        "side": quote.book_side,
        "count": str(quote.quantity),
        "price": str(quote.api_price),
        "time_in_force": "good_till_canceled",
        "expiration_time": int(now) + 3,
        "self_trade_prevention_type": "taker_at_cross",
        "post_only": True,
        "cancel_order_on_pause": True,
        "reduce_only": False,
        "exchange_index": 2,
        "subaccount": 0,
    }


def normalize_order_response(response: dict) -> dict:
    value = response.get("order", response)
    if not isinstance(value, dict):
        raise RuntimeError("Invalid demo order response")
    return value


class Runner:
    def __init__(self, root=None, *, client=None):
        if os.environ.get("LAB_HFT_DEMO_AUTHORIZATION") != AUTHORIZATION:
            raise RuntimeError("Study 029 Demo authorization is missing")
        self.root = Path(root or os.environ.get("LAB_HFT_DEMO_DIR", "/data/hft-demo-029"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = (self.root / "runner.lock").open("a")
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.client = client or DemoHFTClient()
        self.journal = Journal(self.root / "orders.sqlite3")
        identity = hashlib.sha256(self.client.key_id.encode()).hexdigest()
        self.identity_sha256 = identity
        self.journal.register(identity)
        self.cfg = Config()
        self.forecast_cfg = Experiment(max_book_age_ms=1500, max_index_age_ms=2500)
        self.market = MarketState()
        self.current: list[str] = []
        self.discovery_at = 0.0
        self.account_at = 0.0
        self.cash = Decimal(0)
        self.event_counter = 0
        self.status = {
            "study": "029",
            "environment": "Kalshi Demo",
            "strategy": STRATEGY,
            "configuration_revision": CONFIG_REVISION,
            "registration_sha256": registration_hash(),
            "registration": registration(),
            "production_orders_authorized": False,
            "demo_orders_authorized": True,
            "state": "starting",
            "started_ns": time.time_ns(),
        }

    def apply_event(self, kind: str, payload: dict, received_ns: int | None = None):
        self.event_counter += 1
        at = received_ns or time.time_ns()
        self.market.apply(Event(self.event_counter, at, None, kind, payload))

    async def benchmark(self):
        session = 0
        while True:
            session += 1
            try:
                async with connect(
                    WS,
                    additional_headers=self.client.headers("GET", "/trade-api/ws/v2"),
                    ping_interval=15,
                    ping_timeout=15,
                    max_queue=32,
                ) as ws:
                    await ws.send(dumps({
                        "id": 1,
                        "cmd": "subscribe",
                        "params": {"channels": ["cfbenchmarks_value"], "index_ids": ["BRTI"]},
                    }))
                    while True:
                        frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                        if frame.get("type") == "error":
                            raise RuntimeError("Demo BRTI subscription rejected")
                        self.apply_event("ws", {
                            "frame": frame,
                            "session": session,
                            "book_convention": "yes_price",
                        })
                        if frame.get("type") == "cfbenchmarks_value":
                            self.status["benchmark_received_ns"] = time.time_ns()
                            self.status.pop("benchmark_error", None)
            except asyncio.CancelledError:
                raise
            except (httpx.HTTPError, OSError, TimeoutError, ValueError, ConnectionClosed, InvalidStatus) as exc:
                self.status["benchmark_error"] = type(exc).__name__
                self.apply_event("gap", {"stream": "benchmark", "reason": type(exc).__name__})
                await asyncio.sleep(5)

    async def discover(self):
        now = time.time()
        if now - self.discovery_at < 5:
            return
        data = await self.client.get(
            "/markets", {"series_ticker": "KXBTC15M", "status": "open", "limit": 100}
        )
        if data.get("cursor"):
            raise RuntimeError("Unexpected HFT demo discovery pagination")
        current = []
        for item in data.get("markets", []):
            close = close_timestamp(item)
            if (
                item.get("exchange_index") == 2
                and item.get("status") == "active"
                and close is not None
                and now <= close <= now + 1800
            ):
                current.append(item["ticker"])
                self.apply_event("market", {"market": item})
        self.current = sorted(current)
        self.discovery_at = now

    async def account_snapshot(self):
        balance = await self.client.get("/portfolio/balance", {"exchange_index": 2})
        self.cash = Decimal(str(balance["balance_dollars"]))
        if not self.cash.is_finite() or self.cash < 0:
            raise RuntimeError("Invalid HFT Demo balance")
        if self.cash < MAX_GROSS_PREMIUM:
            raise RuntimeError("Insufficient HFT Demo commissioning cash")
        resting = await self.client.get(
            "/portfolio/orders", {"status": "resting", "exchange_index": 2, "limit": 200}
        )
        positions = await self.client.get(
            "/portfolio/positions", {"exchange_index": 2, "limit": 200}
        )
        if resting.get("cursor") or positions.get("cursor"):
            raise RuntimeError("Unexpected HFT Demo account pagination")
        tracked_ids = {row["order_id"] for row in self.journal.active() if row["order_id"]}
        exchange_resting = resting.get("orders", [])
        if any(order.get("order_id") not in tracked_ids for order in exchange_resting):
            raise RuntimeError("External resting Demo order blocks Study 029")
        if {order.get("order_id") for order in exchange_resting} != tracked_ids:
            raise RuntimeError("Durable and exchange resting orders differ")
        expected = self.journal.inventory()
        actual = {}
        for position in positions.get("market_positions", []):
            quantity = Decimal(str(position.get("position_fp", "0")))
            if quantity:
                if quantity != int(quantity):
                    raise RuntimeError("Fractional Demo position")
                actual[position["ticker"]] = int(quantity)
        if actual != expected:
            raise RuntimeError("Durable and exchange Demo positions differ")
        if len(actual) > 1 or self.journal.gross_premium() > MAX_GROSS_PREMIUM:
            raise RuntimeError("HFT Demo risk cap exceeded")
        self.status.update(cash=str(self.cash), account_position=actual)

    def commission(self):
        path = self.root / "COMMISSIONED.json"
        value = {
            "environment": "Kalshi Demo",
            "exchange_index": 2,
            "subaccount": 0,
            "credential_identity_sha256": self.identity_sha256,
            "registration_sha256": registration_hash(),
            "starting_cash": str(self.cash),
        }
        encoded = dumps(value)
        if path.exists() and path.read_text() != encoded:
            raise RuntimeError("HFT Demo commissioning identity changed")
        if not path.exists():
            temporary = self.root / "COMMISSIONED.tmp"
            temporary.write_text(encoded)
            os.replace(temporary, path)
        self.status["commissioned"] = True

    async def settlements(self):
        done = {row["ticker"] for row in self.journal.settlements()}
        tickers = {
            row["ticker"]
            for row in self.journal.rows()
            if row["exchange_order"]
            and Decimal(str(json.loads(row["exchange_order"])["fill_count_fp"])) > 0
        }
        for ticker in sorted(tickers - done):
            response = await self.client.get(
                "/portfolio/settlements", {"ticker": ticker, "exchange_index": 2, "limit": 100}
            )
            if response.get("cursor"):
                raise RuntimeError("Unexpected HFT Demo settlement pagination")
            matches = [
                item
                for item in response.get("settlements", [])
                if item.get("ticker") == ticker and item.get("exchange_index") == 2
            ]
            if len(matches) > 1:
                raise RuntimeError("Multiple HFT Demo settlements for one ticker")
            if not matches:
                continue
            item = matches[0]
            result = str(item.get("market_result", "")).lower()
            if result not in {"yes", "no"}:
                raise RuntimeError("Invalid HFT Demo settlement result")
            fills = self.journal.ticker_fills(ticker)
            pnl = fills[result] - self.journal.ticker_cost(ticker)
            self.journal.record_settlement(ticker, item, pnl)

    async def reconcile(self):
        for row in self.journal.rows():
            if not row["order_id"]:
                if row["state"] in {"intent", "uncertain_create"}:
                    data = await self.client.get(
                        "/portfolio/orders",
                        {"ticker": row["ticker"], "exchange_index": 2, "limit": 200},
                    )
                    matches = [o for o in data.get("orders", []) if o.get("client_order_id") == row["client_id"]]
                    if len(matches) > 1:
                        raise RuntimeError("Duplicate HFT Demo client order ID")
                    if matches:
                        order = matches[0]
                        self.journal.acknowledge_create(row["client_id"], {
                            "order_id": order["order_id"],
                            "client_order_id": row["client_id"],
                            "fill_count": "0",
                            "remaining_count": "1",
                        })
                        self.journal.apply_order(order)
                continue
            if row["state"] not in {"terminal", "rejected"}:
                response = await self.client.get("/portfolio/orders/" + row["order_id"])
                self.journal.apply_order(normalize_order_response(response))
        return not self.journal.unresolved()

    async def cancel_row(self, row: dict):
        self.journal.begin_cancel(row["client_id"])
        try:
            response = await self.client.cancel(row["order_id"], row["ticker"])
            response = response.get("order", response)
            self.journal.acknowledge_cancel(row["client_id"], response)
        except httpx.HTTPStatusError as exc:
            self.journal.cancel_error(row["client_id"], "HTTP_" + str(exc.response.status_code))
        except httpx.RequestError as exc:
            self.journal.cancel_error(row["client_id"], type(exc).__name__)

    async def cancel_all(self):
        for row in list(self.journal.active()):
            await self.cancel_row(row)

    async def submit(self, quote, decision):
        payload = make_payload(quote)
        serial = json.loads(dumps(decision.__dict__))
        self.journal.begin_create(payload, serial, quote.outcome)
        try:
            response = normalize_order_response(await self.client.create(payload))
            self.journal.acknowledge_create(payload["client_order_id"], {
                "order_id": response["order_id"],
                "client_order_id": response["client_order_id"],
                "fill_count": response.get("fill_count_fp", response.get("fill_count", "0")),
                "remaining_count": response.get("remaining_count_fp", response.get("remaining_count", "1")),
            })
            self.journal.apply_order(response)
        except httpx.HTTPStatusError as exc:
            definitive = exc.response.status_code in {400, 401, 403, 409, 422, 429}
            self.journal.create_error(
                payload["client_order_id"], "HTTP_" + str(exc.response.status_code), definitive=definitive
            )
            if exc.response.status_code in {401, 403}:
                raise RuntimeError("Demo credential lacks order permission") from None
        except httpx.RequestError as exc:
            self.journal.create_error(payload["client_order_id"], type(exc).__name__, definitive=False)

    async def quote_market(self, ticker: str):
        now_ns = time.time_ns()
        forecast = self.market.forecast(ticker, now_ns, self.forecast_cfg, adaptive=True)
        if forecast is None:
            self.status["last_rejections"] = ["forecast_unavailable"]
            return
        received_ns = time.time_ns()
        data = await self.client.get("/markets/" + ticker + "/orderbook", {"depth": 10})
        inventory = self.journal.inventory().get(ticker, 0)
        # A Kalshi book can legitimately be one-sided between updates.  It is
        # unusable for a two-sided fair-value quote, but it must never take
        # down the runner or turn into a blind order.
        try:
            snapshot = parse_top(data, received_ns, ticker, forecast["yes_probability"], inventory)
        except (KeyError, TypeError, ValueError):
            self.status["last_rejections"] = ["one_sided_or_invalid_book"]
            return
        snapshot = Snapshot(
            **{**snapshot.__dict__, "seconds_left": forecast["seconds_left"]}
        )
        decision = decide(snapshot, self.cfg)
        self.status["last_decision"] = json.loads(dumps(decision.__dict__))
        self.status["last_rejections"] = list(decision.rejections)
        wanted = {(q.outcome, str(q.api_price)): q for q in decision.quotes}
        for row in list(self.journal.active(ticker)):
            payload = json.loads(row["payload"])
            if (row["outcome"], payload["price"]) not in wanted:
                await self.cancel_row(row)
        if self.journal.unresolved():
            return
        active = {(row["outcome"], json.loads(row["payload"])["price"]) for row in self.journal.active(ticker)}
        for key, quote in wanted.items():
            if key not in active and len(self.journal.active()) < 2:
                await self.submit(quote, decision)
                if self.journal.unresolved():
                    return

    async def step(self):
        await self.discover()
        if not await self.reconcile():
            self.status["state"] = "blocked_unconfirmed_order"
            return
        await self.settlements()
        await self.account_snapshot()
        self.commission()
        if (self.root / "STOP").exists() or (self.root / "PAUSE_QUOTES").exists():
            await self.cancel_all()
            self.status["state"] = "stopped_by_file" if (self.root / "STOP").exists() else "quotes_paused"
            return
        exchange = await self.client.get("/exchange/status")
        shards = [x for x in exchange.get("exchange_index_statuses", []) if x.get("exchange_index") == 2]
        if (
            not exchange.get("exchange_active")
            or not exchange.get("trading_active")
            or len(shards) != 1
            or not shards[0].get("exchange_active")
            or not shards[0].get("trading_active")
        ):
            await self.cancel_all()
            self.status["state"] = "exchange_paused"
            return
        self.status["state"] = "watching"
        self.status["markets"] = self.current
        if not self.current:
            await self.cancel_all()
            return
        ticker = self.current[0]
        for row in list(self.journal.active()):
            if row["ticker"] != ticker:
                await self.cancel_row(row)
        if not self.journal.unresolved():
            await self.quote_market(ticker)

    def snapshot(self):
        self.status.update(
            updated_ns=time.time_ns(),
            safety={
                "maximum_inventory": self.cfg.maximum_inventory,
                "maximum_markets_with_inventory": 1,
                "maximum_resting_orders": 2,
                "maximum_gross_premium_dollars": str(MAX_GROSS_PREMIUM),
                "stop_exists": (self.root / "STOP").exists(),
                "pause_quotes_exists": (self.root / "PAUSE_QUOTES").exists(),
            },
            journal=self.journal.summary(),
        )
        temporary = self.root / "status.tmp"
        temporary.write_text(dumps(self.status))
        os.replace(temporary, self.root / "status.json")
        return self.status

    async def loop(self):
        while True:
            try:
                await self.step()
                self.status.pop("error", None)
            except asyncio.CancelledError:
                raise
            except (httpx.HTTPError, TimeoutError) as exc:
                self.status.update(state="waiting_api", error=type(exc).__name__)
            except Exception as exc:
                self.status.update(state="stopped_error", error=f"{type(exc).__name__}: {exc}")
                self.snapshot()
                raise
            self.snapshot()
            await asyncio.sleep(1)

    async def run(self):
        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(self.benchmark())
                group.create_task(self.loop())
        finally:
            await self.client.close()
            self.journal.close()
            self.lock.close()

