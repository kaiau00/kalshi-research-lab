"""Exact, rebuildable local cache for receipt-ordered HFT replay events."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zlib
from collections.abc import Iterable, Iterator
from pathlib import Path

from research_lab.storage import Event, canonical

CACHE_FORMAT = "hft-normalized-tape-v1"


def _connect(path: Path) -> sqlite3.Connection:
    database = sqlite3.connect(path)
    database.execute("PRAGMA journal_mode=WAL")
    database.execute("PRAGMA synchronous=FULL")
    database.executescript(
        """CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
           CREATE TABLE events (
             position INTEGER PRIMARY KEY, event_id INTEGER NOT NULL,
             received_ns INTEGER NOT NULL, source_ns INTEGER, kind TEXT NOT NULL,
             payload BLOB NOT NULL, digest TEXT NOT NULL
           );"""
    )
    return database


def write_cache(path: Path, events: Iterable[Event], source: dict) -> dict:
    """Write an exact merged-event cache once; refuse to overwrite evidence."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"Normalized replay cache already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    database = _connect(path)
    order_hash = hashlib.sha256()
    count = 0
    first_ns = last_ns = None
    try:
        for count, event in enumerate(events, start=1):
            envelope = [count, event.id, event.received_ns, event.source_ns, event.kind, event.payload, event.digest]
            order_hash.update(canonical(envelope))
            database.execute(
                "INSERT INTO events VALUES(?,?,?,?,?,?,?)",
                (
                    count,
                    event.id,
                    event.received_ns,
                    event.source_ns,
                    event.kind,
                    zlib.compress(canonical(event.payload)),
                    event.digest,
                ),
            )
            first_ns = event.received_ns if first_ns is None else first_ns
            last_ns = event.received_ns
        metadata = {
            "format": CACHE_FORMAT,
            "source": source,
            "event_count": count,
            "first_ns": first_ns,
            "last_ns": last_ns,
            "merged_order_sha256": order_hash.hexdigest(),
        }
        database.executemany(
            "INSERT INTO metadata VALUES(?,?)",
            ((key, json.dumps(value, sort_keys=True)) for key, value in metadata.items()),
        )
        database.commit()
        return metadata
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        if database:
            database.close()


def metadata(path: Path) -> dict:
    database = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
    try:
        value = {key: json.loads(raw) for key, raw in database.execute("SELECT key,value FROM metadata")}
    finally:
        database.close()
    if value.get("format") != CACHE_FORMAT:
        raise ValueError("Unknown normalized replay cache format")
    return value


def cached_events(path: Path) -> Iterator[Event]:
    """Yield the original receipt-ordered events without re-merging archives."""
    database = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
    try:
        for row in database.execute(
            "SELECT event_id,received_ns,source_ns,kind,payload,digest FROM events ORDER BY position"
        ):
            event_id, received_ns, source_ns, kind, payload, digest = row
            yield Event(event_id, received_ns, source_ns, kind, json.loads(zlib.decompress(payload)), digest)
    finally:
        database.close()
