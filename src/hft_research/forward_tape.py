"""Read-only forward recorder for synchronized book, trade and BRTI evidence."""

from __future__ import annotations

import asyncio
import io
import json
import time
import uuid
from collections import Counter
from pathlib import Path

import zstandard
from websockets.asyncio.client import connect

from research_lab.recorder import WS_URL, Recorder, load_signer
from research_lab.storage import Store, canonical

from .registration import registration, registration_hash
from .tape import parse_public_trade

TAPE_SCHEMA = "hft-forward-tape-v1"


def initial_registration():
    return (
        "hft_tape_registration",
        {
            "schema": TAPE_SCHEMA,
            "study_registration": registration(),
            "study_registration_sha256": registration_hash(),
            "channels": ["orderbook_delta", "trade", "cfbenchmarks_value"],
            "production_orders_authorized": False,
            "demo_orders_authorized": False,
        },
    )


def market_subscription(tickers):
    tickers = sorted(tickers)
    if not tickers or any(not ticker.startswith("KXBTC15M-") for ticker in tickers):
        raise ValueError("Forward tape requires explicit KXBTC15M tickers")
    return {
        "channels": ["orderbook_delta", "trade"],
        "market_tickers": tickers,
        "use_yes_price": True,
    }


def subscription_updates(sids, tickers, action, first_request_id):
    """Kalshi currently requires one SID per update command."""

    if action not in {"add_markets", "delete_markets"}:
        raise ValueError("Unsupported subscription update")
    tickers = sorted(tickers)
    if not tickers:
        return []
    return [
        {
            "id": first_request_id + offset,
            "cmd": "update_subscription",
            "params": {"sid": sid, "market_tickers": tickers, "action": action},
        }
        for offset, sid in enumerate(sorted(sids), start=1)
    ]


class ForwardTapeRecorder(Recorder):
    """Recorder with no portfolio or order API surface."""

    def __init__(self, path: Path, *, max_storage_bytes=256_000_000):
        super().__init__(
            path,
            segmented=False,
            initial_registration=initial_registration(),
        )
        self.max_bytes = max_storage_bytes
        self.status.update(
            trade_messages=0,
            non_block_trade_messages=0,
            block_trade_messages=0,
            invalid_trade_messages=0,
            market_connection="waiting",
        )

    def record_market_frame(self, frame, session, subscribed):
        msg = frame.get("msg") or {}
        source_ns = int(msg["ts_ms"]) * 1_000_000 if msg.get("ts_ms") else None
        event = self.append(
            "ws",
            {"frame": frame, "session": session, "book_convention": "yes_price"},
            source_ns,
        )
        if frame.get("type") == "trade":
            try:
                trade = parse_public_trade(frame, subscribed)
            except ValueError:
                self.status["invalid_trade_messages"] += 1
                raise
            self.status["trade_messages"] += 1
            key = "block_trade_messages" if trade.is_block_trade else "non_block_trade_messages"
            self.status[key] += 1
        return event

    async def market_stream(self):
        delay = 1
        while True:
            try:
                signer = load_signer()
                if signer is None:
                    await asyncio.sleep(10)
                    continue
                if not self.watch:
                    await asyncio.sleep(1)
                    continue
                session = uuid.uuid4().hex
                sequences, channel_sids, request_id = {}, {}, 1
                subscribed = set(self.watch)
                self.status["market_connection"] = "connecting"
                async with connect(
                    WS_URL,
                    additional_headers=signer(),
                    ping_interval=15,
                    ping_timeout=15,
                    max_size=4 * 1024 * 1024,
                    max_queue=256,
                ) as ws:
                    self.append(
                        "gap",
                        {"reason": "new_stream_session", "session": session, "stream": "hft_market"},
                    )
                    await ws.send(json.dumps({
                        "id": request_id,
                        "cmd": "subscribe",
                        "params": market_subscription(subscribed),
                    }))
                    last_data = time.monotonic()
                    while True:
                        if len(channel_sids) == 2:
                            add = self.watch - subscribed
                            remove = subscribed - self.watch
                            for action, tickers in (
                                ("add_markets", add),
                                ("delete_markets", remove if self.watch else set()),
                            ):
                                if tickers:
                                    updates = subscription_updates(
                                        channel_sids.values(), tickers, action, request_id,
                                    )
                                    for update in updates:
                                        await ws.send(json.dumps(update))
                                    request_id += len(updates)
                                    if action == "add_markets":
                                        subscribed |= tickers
                                    else:
                                        subscribed -= tickers
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=0.25)
                        except TimeoutError:
                            if time.monotonic() - last_data > 30 and self.current:
                                raise RuntimeError("hft_market_stream_no_data")
                            continue
                        last_data = time.monotonic()
                        frame = json.loads(raw)
                        msg = frame.get("msg") or {}
                        if frame.get("type") == "subscribed":
                            channel = msg.get("channel")
                            sid = msg.get("sid", frame.get("sid"))
                            if channel in {"orderbook_delta", "trade"} and sid is not None:
                                channel_sids[channel] = int(sid)
                        self.record_market_frame(frame, session, subscribed)
                        if frame.get("type") == "error":
                            raise RuntimeError("hft_market_subscription_error")
                        if "sid" in frame and "seq" in frame:
                            stream_id, current = int(frame["sid"]), int(frame["seq"])
                            if stream_id in sequences and current != sequences[stream_id] + 1:
                                raise RuntimeError("hft_market_sequence_gap")
                            sequences[stream_id] = current
                        self.status.update(last_ws_ns=time.time_ns(), mode="recording", error=None)
                        self.status["market_connection"] = "connected"
                        delay = 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                reason = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
                self.status.update(error=reason, market_connection="reconnecting")
                self.append("gap", {"reason": reason, "stream": "hft_market"})
                self.store.commit()
                if reason.endswith("_reached"):
                    raise
                await asyncio.sleep(delay)
                delay = min(60, delay * 2)

    async def run(self):
        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(self.discover())
                group.create_task(self.resolve())
                group.create_task(self.fees())
                group.create_task(self.stream("benchmark"))
                group.create_task(self.market_stream())
                group.create_task(self.heartbeat())
        finally:
            self.status["mode"] = "stopped"
            await self.client.close()
            self.store.close()


def summarize_tape(path: Path):
    """Verify a capture and estimate compact archive rates from actual bytes."""

    store = Store(path, readonly=True)
    compressed = io.BytesIO()
    component_buffers = {
        "trade": io.BytesIO(),
        "book": io.BytesIO(),
        "benchmark": io.BytesIO(),
        "other": io.BytesIO(),
    }
    frame_types = Counter()
    trade_ids = set()
    duplicate_trade_ids = 0
    first_ns = None
    last_ns = None
    event_count = 0
    try:
        integrity = store.verify()
        component_streams = {
            name: zstandard.ZstdCompressor(level=9).stream_writer(buffer, closefd=False)
            for name, buffer in component_buffers.items()
        }
        with zstandard.ZstdCompressor(level=9).stream_writer(compressed, closefd=False) as stream:
            for event in store.events():
                event_count += 1
                first_ns = event.received_ns if first_ns is None else first_ns
                last_ns = event.received_ns
                row = canonical([
                    event.id,
                    event.received_ns,
                    event.source_ns,
                    event.kind,
                    event.payload,
                ]) + b"\n"
                stream.write(row)
                if event.kind == "ws":
                    frame = event.payload.get("frame") or {}
                    frame_type = frame.get("type", "missing")
                    frame_types[frame_type] += 1
                    if frame_type == "trade":
                        component = "trade"
                        trade_id = (frame.get("msg") or {}).get("trade_id")
                        if trade_id in trade_ids:
                            duplicate_trade_ids += 1
                        trade_ids.add(trade_id)
                    elif frame_type in {"orderbook_delta", "orderbook_snapshot"}:
                        component = "book"
                    elif frame_type == "cfbenchmarks_value":
                        component = "benchmark"
                    else:
                        component = "other"
                else:
                    component = "other"
                component_streams[component].write(row)
        for component_stream in component_streams.values():
            component_stream.close()
        elapsed_seconds = max(0.0, ((last_ns or 0) - (first_ns or 0)) / 1_000_000_000)
        archive_bytes = len(compressed.getvalue())
        scale = 86_400 / elapsed_seconds if elapsed_seconds else 0.0
        component_rates = {
            name: {
                "capture_bytes": len(buffer.getvalue()),
                "projected_bytes_per_day": round(len(buffer.getvalue()) * scale) if scale else None,
                "projected_gb_per_30_days": (
                    round(len(buffer.getvalue()) * scale * 30 / 1_000_000_000, 4)
                    if scale else None
                ),
            }
            for name, buffer in component_buffers.items()
        }
        return {
            "schema": TAPE_SCHEMA,
            "integrity": integrity,
            "events": event_count,
            "elapsed_seconds": round(elapsed_seconds, 6),
            "frame_types": dict(sorted(frame_types.items())),
            "unique_trade_ids": len(trade_ids),
            "duplicate_trade_ids": duplicate_trade_ids,
            "sqlite_bytes": store.stats()["bytes"],
            "zstd_archive_bytes": archive_bytes,
            "projected_zstd_bytes_per_day": round(archive_bytes * scale) if scale else None,
            "projected_zstd_gb_per_30_days": (
                round(archive_bytes * scale * 30 / 1_000_000_000, 4) if scale else None
            ),
            "component_zstd_rates": component_rates,
        }
    finally:
        store.close()
