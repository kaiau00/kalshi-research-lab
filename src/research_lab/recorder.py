from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import uuid
import zlib
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from websockets.asyncio.client import connect

from .market import MarketState, epoch_ns
from .storage import Store

LOG = logging.getLogger(__name__)
REST_BASE = "https://external-api.kalshi.com/trade-api/v2"
WS_URL = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
SERIES = "KXBTC15M"


class MarketDataClient:
    """Market data only. No account, portfolio, or exchange order methods."""

    def __init__(self):
        self.http = httpx.AsyncClient(timeout=20, follow_redirects=False)

    async def get(self, path, params=None):
        if not path.startswith(("/markets", "/historical/", "/series/", "/exchange/")) or ":" in path:
            raise ValueError("Only market-data GET endpoints are allowed")
        for attempt in range(4):
            response = await self.http.get(REST_BASE + path, params=params)
            if response.status_code == 429 or response.status_code >= 500:
                await asyncio.sleep(min(10, 2 ** attempt))
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError("Market-data retries exhausted")

    async def markets(self, **params):
        return await self.get("/markets", {"series_ticker": SERIES, "limit": 200, **params})

    async def close(self):
        await self.http.aclose()


def load_signer():
    key_id = os.environ.get("KALSHI_API_KEY_ID", "").strip()
    pem = os.environ.get("KALSHI_PRIVATE_KEY_PEM", "")
    b64 = os.environ.get("KALSHI_PRIVATE_KEY_B64", "")
    key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "")
    if not key_id or not (pem or b64 or key_path):
        return None
    raw = pem.encode() if pem else base64.b64decode(b64, validate=True) if b64 else Path(key_path).read_bytes()
    key = serialization.load_pem_private_key(raw, password=None)

    def headers():
        stamp = str(int(time.time() * 1000))
        message = (stamp + "GET" + "/trade-api/ws/v2").encode()
        signature = key.sign(message, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256())
        return {"KALSHI-ACCESS-KEY": key_id, "KALSHI-ACCESS-TIMESTAMP": stamp,
                "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode()}
    return headers


class Recorder:
    def __init__(self, path: Path):
        self.store = Store(path)
        if self.store.prefix()['last_event_id'] == 0:
            from .research import source_hash
            from .settings import Experiment
            self.store.append('experiment_registration', {'config': Experiment().to_dict(),
                                                          'source_sha256': source_hash()})
            self.store.commit()
        self.client = MarketDataClient()
        self.current = set()
        self.last_series = 0
        self.resolve_cursor = 0
        latest = [json.loads(zlib.decompress(row[0])) for row in
                  self.store.conn.execute('SELECT payload FROM latest_markets')]
        self.pending = {m['ticker'] for m in latest if not m.get('result')}
        self.state = MarketState()
        self.status = {"mode": "waiting_for_credentials", "last_discovery_ns": None,
                       "last_ws_ns": None, "last_benchmark_ns": None, "error": None}
        self.max_bytes = int(os.environ.get("LAB_MAX_STORAGE_BYTES", "2000000000"))
        self.last_commit = time.monotonic()

    def append(self, kind, payload, source_ns=None):
        event = self.store.append(kind, payload, source_ns=source_ns)
        self.state.apply(event)
        if time.monotonic() - self.last_commit >= 1:
            if self.store.stats()["bytes"] >= self.max_bytes:
                raise RuntimeError("storage_limit_reached")
            self.store.commit()
            self.last_commit = time.monotonic()
        return event

    async def discover(self):
        while True:
            try:
                if time.monotonic() - self.last_series >= 900:
                    series = await self.client.get('/series/' + SERIES)
                    self.append('series', {'series': series['series']})
                    self.last_series = time.monotonic()
                result = await self.client.markets(status="open")
                markets = result.get("markets", [])
                if result.get("cursor"):
                    raise RuntimeError("Unexpected BTC discovery pagination")
                active = set()
                for market in markets:
                    self.append("market", {"market": market})
                    ticker = market["ticker"]
                    self.pending.add(ticker)
                    if epoch_ns(market["close_time"]) > time.time_ns():
                        active.add(ticker)
                self.current = active
                # Bounded old-market resolution work per cycle; official results only.
                unresolved = sorted(self.pending - active)
                offset = self.resolve_cursor % max(1, len(unresolved))
                batch = (unresolved[offset:] + unresolved[:offset])[:12]
                self.resolve_cursor += len(batch)
                for ticker in batch:
                    try:
                        try:
                            result = await self.client.get("/markets/" + ticker)
                        except httpx.HTTPStatusError as exc:
                            if exc.response.status_code != 404:
                                raise
                            result = await self.client.get("/historical/markets/" + ticker)
                    except (httpx.HTTPError, RuntimeError) as exc:
                        self.append('resolution_error', {'ticker': ticker, 'error': type(exc).__name__})
                        continue
                    market = result.get("market", result)
                    self.append("market", {"market": market})
                    if market.get("result") in ("yes", "no"):
                        self.pending.discard(ticker)
                self.status["last_discovery_ns"] = time.time_ns()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.status["error"] = type(exc).__name__
                LOG.warning("Market discovery failed: %s", type(exc).__name__)
                if str(exc) == "storage_limit_reached":
                    raise
            await asyncio.sleep(30)

    async def stream(self):
        delay = 1
        while True:
            try:
                signer = load_signer()
                if signer is None:
                    self.status["mode"] = "waiting_for_credentials"
                    await asyncio.sleep(10)
                    continue
                if not self.current:
                    self.status["mode"] = "waiting_for_market"
                    await asyncio.sleep(5)
                    continue
                self.status["mode"] = "connecting"
                session = uuid.uuid4().hex
                subscribed = set(self.current)
                seq = {}
                async with connect(WS_URL, additional_headers=signer(), ping_interval=15,
                                   ping_timeout=15, max_size=4 * 1024 * 1024, max_queue=128) as ws:
                    self.append("gap", {"reason": "new_stream_session", "session": session})
                    await ws.send(json.dumps({"id": 1, "cmd": "subscribe", "params": {
                        "channels": ["orderbook_delta"], "market_tickers": sorted(subscribed),
                        "use_yes_price": True}}))
                    await ws.send(json.dumps({"id": 2, "cmd": "subscribe", "params": {
                        "channels": ["cfbenchmarks_value"], "index_ids": ["BRTI"]}}))
                    await ws.send(json.dumps({"id": 3, "cmd": "subscribe", "params": {
                        "channels": ["trade"], "market_tickers": sorted(subscribed)}}))
                    self.status["mode"] = "connected_waiting_for_data"
                    last_data = time.monotonic()
                    while self.current == subscribed:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=1)
                        except TimeoutError:
                            if time.monotonic() - last_data > 30:
                                raise RuntimeError("stream_no_data")
                            continue
                        last_data = time.monotonic()
                        frame = json.loads(raw)
                        source_ns = None
                        msg = frame.get("msg") or {}
                        if msg.get("ts_ms"):
                            source_ns = int(msg["ts_ms"]) * 1_000_000
                        if frame.get("type") == "cfbenchmarks_value":
                            try:
                                data = json.loads(msg["data"]) if isinstance(msg["data"], str) else msg["data"]
                                source_ns = int(data["time"]) * 1_000_000
                                self.status["last_benchmark_ns"] = time.time_ns()
                            except (KeyError, TypeError, ValueError):
                                pass
                        self.append("ws", {"frame": frame, "session": session,
                                           "book_convention": "yes_price"}, source_ns)
                        if frame.get("type") == "error":
                            # Never log the raw upstream error, which may include request details.
                            raise RuntimeError("subscription_error")
                        if "sid" in frame and "seq" in frame:
                            sid, cur = int(frame["sid"]), int(frame["seq"])
                            if sid in seq and cur != seq[sid] + 1 and cur > seq[sid]:
                                raise RuntimeError("sequence_gap")
                            seq[sid] = max(seq.get(sid, cur), cur)
                        self.status.update(last_ws_ns=time.time_ns(), mode="recording", error=None)
                        delay = 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.status.update(mode="reconnecting", error=type(exc).__name__)
                self.append("gap", {"reason": type(exc).__name__})
                self.store.commit()
                LOG.warning("Stream reconnect: %s", type(exc).__name__)
                if str(exc) == "storage_limit_reached":
                    raise
                await asyncio.sleep(delay)
                delay = min(60, delay * 2)

    async def heartbeat(self):
        while True:
            self.append("heartbeat", {"mode": self.status["mode"]})
            self.store.commit()
            await asyncio.sleep(30)

    async def run(self):
        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(self.discover())
                group.create_task(self.stream())
                group.create_task(self.heartbeat())
        finally:
            self.status["mode"] = "stopped"
            await self.client.close()
            self.store.close()
