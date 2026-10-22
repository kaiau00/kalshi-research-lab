"""Trade-only read path for queue-evidence research; it has no order API."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections import OrderedDict
from pathlib import Path

from websockets.asyncio.client import connect

from research_lab.recorder import WS_URL, load_signer
from research_lab.segments import SegmentedStore, enough_disk

from .provenance import TRADE_TAPE_FORMAT, trade_tape_registration, trade_tape_source_hash
from .registration import registration_hash
from .tape import parse_public_trade, trade_subscription


def advance_sequence(previous, frame, sid):
    """Validate the one subscribed stream without assuming control-frame sequencing."""

    if sid is None or frame.get("sid") != sid or "seq" not in frame:
        return previous
    current = int(frame["seq"])
    if previous is not None and current != previous + 1:
        raise RuntimeError("hft_trade_sequence_gap")
    return current


class TradeTapeSidecar:
    """Capture public trades for the current recorder watch set."""

    def __init__(self, root: Path, watch_provider):
        self.root = Path(root)
        self.watch_provider = watch_provider
        self.source_sha256 = trade_tape_source_hash()
        self.store = SegmentedStore(self.root)
        # The trade feed can be materially busier than the shared book recorder.
        # Rotate it independently so a single open segment cannot consume the
        # sidecar's entire hot-storage allowance before it becomes archivable.
        self.store.limit = int(os.environ.get("LAB_HFT_TRADE_SEGMENT_EVENTS", "100000"))
        self.store.seconds = int(os.environ.get("LAB_HFT_TRADE_SEGMENT_SECONDS", "300"))
        self._register()
        self.max_bytes = int(os.environ.get("LAB_HFT_TRADE_HOT_MAX_BYTES", "256000000"))
        self.archive_max_bytes = int(
            os.environ.get("LAB_HFT_TRADE_ARCHIVE_MAX_BYTES", "5000000000")
        )
        self.last_commit = time.monotonic()
        self.trade_ids = OrderedDict()
        self.trade_id_cache_limit = 100_000
        self.status = {
            "state": "waiting_for_credentials",
            "connection": "waiting",
            "format": TRADE_TAPE_FORMAT,
            "study_registration_sha256": registration_hash(),
            "source_sha256": self.source_sha256,
            "trade_messages": 0,
            "non_block_trade_messages": 0,
            "block_trade_messages": 0,
            "duplicate_trade_ids": 0,
            "invalid_trade_messages": 0,
            "last_trade_ns": None,
            "last_ws_ns": None,
            "error": None,
            "production_orders_authorized": False,
            "demo_orders_authorized": False,
            "limits": {
                "segment_events": self.store.limit,
                "segment_seconds": self.store.seconds,
                "hot_max_bytes": self.max_bytes,
                "archive_max_bytes": self.archive_max_bytes,
            },
        }

    def _register(self):
        settings = {
            "format": TRADE_TAPE_FORMAT,
            "study_registration_sha256": registration_hash(),
            "source_sha256": self.source_sha256,
        }
        for key, value in settings.items():
            row = self.store.cat.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            if row and row[0] != value:
                self.store.close()
                raise RuntimeError("HFT trade-tape registration changed")
            self.store.cat.execute("INSERT OR IGNORE INTO settings VALUES(?,?)", (key, value))
        self.store.cat.commit()
        if self.store.prefix()["last_event_id"] == 0:
            self.store.append(
                "hft_trade_registration",
                trade_tape_registration(self.store.dataset, self.source_sha256),
            )
            self.store.commit()

    def watch(self):
        tickers = set(self.watch_provider() or ())
        if any(not ticker.startswith("KXBTC15M-") for ticker in tickers):
            raise RuntimeError("HFT trade-tape watch set escaped KXBTC15M")
        return tickers

    def _hot_bytes(self):
        return sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())

    def _check_capacity(self):
        if self._hot_bytes() >= self.max_bytes:
            raise RuntimeError("hft_trade_hot_storage_limit_reached")
        if not enough_disk(self.root):
            raise RuntimeError("hft_trade_disk_reserve_reached")

    def append(self, kind, payload, *, source_ns=None):
        event = self.store.append(kind, payload, source_ns=source_ns)
        if time.monotonic() - self.last_commit >= 1:
            self._check_capacity()
            self.store.commit()
            self.last_commit = time.monotonic()
        return event

    def record_frame(self, frame, session, subscribed):
        msg = frame.get("msg") or {}
        source_ns = int(msg["ts_ms"]) * 1_000_000 if frame.get("type") == "trade" else None
        event = self.append("ws", {"frame": frame, "session": session}, source_ns=source_ns)
        if frame.get("type") != "trade":
            return event
        try:
            trade = parse_public_trade(frame, subscribed)
        except ValueError:
            self.status["invalid_trade_messages"] += 1
            raise
        if trade.trade_id in self.trade_ids:
            self.status["duplicate_trade_ids"] += 1
        else:
            self.trade_ids[trade.trade_id] = None
            if len(self.trade_ids) > self.trade_id_cache_limit:
                self.trade_ids.popitem(last=False)
        self.status["trade_messages"] += 1
        key = "block_trade_messages" if trade.is_block_trade else "non_block_trade_messages"
        self.status[key] += 1
        self.status["last_trade_ns"] = event.received_ns
        return event

    async def stream(self):
        delay = 1
        while True:
            try:
                signer = load_signer()
                if signer is None:
                    self.status.update(state="waiting_for_credentials", connection="waiting")
                    await asyncio.sleep(10)
                    continue
                initial = self.watch()
                if not initial:
                    self.status.update(state="waiting_for_markets", connection="waiting")
                    await asyncio.sleep(1)
                    continue
                session = uuid.uuid4().hex
                subscribed = set(initial)
                sid = None
                request_id = 1
                sequence = None
                self.status.update(state="connecting", connection="connecting")
                async with connect(
                    WS_URL,
                    additional_headers=signer(),
                    ping_interval=15,
                    ping_timeout=15,
                    max_size=4 * 1024 * 1024,
                    max_queue=256,
                ) as ws:
                    self.append("gap", {
                        "reason": "new_stream_session",
                        "session": session,
                        "stream": "hft_public_trades",
                    })
                    await ws.send(json.dumps({
                        "id": request_id,
                        "cmd": "subscribe",
                        "params": trade_subscription(subscribed),
                    }))
                    last_data = time.monotonic()
                    while True:
                        current = self.watch()
                        if sid is not None:
                            for action, tickers in (
                                ("add_markets", current - subscribed),
                                ("delete_markets", subscribed - current),
                            ):
                                if not tickers:
                                    continue
                                request_id += 1
                                await ws.send(json.dumps({
                                    "id": request_id,
                                    "cmd": "update_subscription",
                                    "params": {
                                        "sid": sid,
                                        "market_tickers": sorted(tickers),
                                        "action": action,
                                    },
                                }))
                                if action == "add_markets":
                                    subscribed |= tickers
                                else:
                                    subscribed -= tickers
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=0.25)
                        except TimeoutError:
                            if time.monotonic() - last_data > 30:
                                raise RuntimeError("hft_trade_stream_no_data")
                            continue
                        last_data = time.monotonic()
                        frame = json.loads(raw)
                        msg = frame.get("msg") or {}
                        if frame.get("type") == "subscribed" and msg.get("channel") == "trade":
                            sid = int(msg.get("sid", frame.get("sid")))
                        self.record_frame(frame, session, subscribed)
                        if frame.get("type") == "error":
                            raise RuntimeError("hft_trade_subscription_error")
                        sequence = advance_sequence(sequence, frame, sid)
                        self.status.update(
                            state="recording",
                            connection="connected",
                            last_ws_ns=time.time_ns(),
                            error=None,
                        )
                        delay = 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                reason = str(exc) if isinstance(exc, RuntimeError) else f"{type(exc).__name__}: {exc}"
                self.status.update(state="reconnecting", connection="reconnecting", error=reason)
                self.append("gap", {"reason": reason, "stream": "hft_public_trades"})
                self.store.commit()
                if reason.endswith("_reached"):
                    raise
                await asyncio.sleep(delay)
                delay = min(60, delay * 2)

    async def run(self):
        try:
            await self.stream()
        finally:
            self.status.update(state="stopped", connection="stopped")
            self.store.close()

    def snapshot(self):
        try:
            storage = self.store.stats()
        except Exception:
            storage = None
        return {**self.status, "storage": storage}
