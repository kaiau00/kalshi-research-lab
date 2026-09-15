from __future__ import annotations

import fcntl
import hashlib
import json
import sqlite3
import time
import zlib
from dataclasses import dataclass
from pathlib import Path


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


@dataclass(frozen=True)
class Event:
    id: int
    received_ns: int
    source_ns: int | None
    kind: str
    payload: dict
    digest: str = ""


class Store:
    """Single writer, many read-only readers; compressed raw events with a hash chain."""

    def __init__(self, path: Path, *, readonly=False):
        self.path = Path(path)
        self.readonly = readonly
        if not readonly:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.lock = self.path.with_suffix(self.path.suffix + '.lock').open('a')
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.lock.close()
                raise RuntimeError('Another recorder already owns this database') from None
        self.conn = sqlite3.connect(
            self.path.resolve().as_uri() + ("?mode=ro" if readonly else "?mode=rwc"),
            uri=True, timeout=10,
        )
        self.conn.execute("PRAGMA busy_timeout=10000")
        if readonly:
            self.conn.execute("PRAGMA query_only=ON")
        else:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=FULL")
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, received_ns INTEGER NOT NULL,
                    source_ns INTEGER, kind TEXT NOT NULL, payload BLOB NOT NULL,
                    digest TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS counts (
                    kind TEXT PRIMARY KEY, n INTEGER NOT NULL,
                    first_ns INTEGER NOT NULL, last_ns INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS latest_markets (
                    ticker TEXT PRIMARY KEY, payload BLOB NOT NULL
                );
                PRAGMA user_version=1;
            """)
            self.conn.commit()
        tail = self.conn.execute("SELECT received_ns,digest FROM events ORDER BY id DESC LIMIT 1").fetchone()
        self.last_ns, self.digest = tail if tail else (0, "0" * 64)

    def append(self, kind, payload, *, received_ns=None, source_ns=None) -> Event:
        if self.readonly:
            raise RuntimeError("Read-only store")
        received_ns = time.time_ns() if received_ns is None else received_ns
        # Preserve insertion order on a wall-clock adjustment; record original receipt too.
        if received_ns < self.last_ns:
            payload = {**payload, "_clock_adjustment_received_ns": received_ns}
            received_ns = self.last_ns
        envelope = [received_ns, source_ns, kind, payload]
        raw = canonical(envelope)
        digest = hashlib.sha256(bytes.fromhex(self.digest) + raw).hexdigest()
        cur = self.conn.execute(
            "INSERT INTO events(received_ns,source_ns,kind,payload,digest) VALUES(?,?,?,?,?)",
            (received_ns, source_ns, kind, zlib.compress(canonical(payload)), digest),
        )
        self.conn.execute("""INSERT INTO counts VALUES(?,1,?,?)
            ON CONFLICT(kind) DO UPDATE SET n=n+1,last_ns=excluded.last_ns""",
            (kind, received_ns, received_ns))
        if kind == 'market':
            self.conn.execute('INSERT OR REPLACE INTO latest_markets VALUES(?,?)',
                              (payload['market']['ticker'], zlib.compress(canonical(payload['market']))))
        self.last_ns, self.digest = received_ns, digest
        return Event(cur.lastrowid, received_ns, source_ns, kind, payload, digest)

    def commit(self):
        if not self.readonly:
            self.conn.commit()

    def prefix(self):
        row = self.conn.execute("SELECT id,digest FROM events ORDER BY id DESC LIMIT 1").fetchone()
        return {"last_event_id": row[0], "sha256_chain": row[1]} if row else {
            "last_event_id": 0, "sha256_chain": "0" * 64,
        }

    def events(self, end_id=None):
        end_id = self.prefix()["last_event_id"] if end_id is None else end_id
        for row in self.conn.execute("SELECT * FROM events WHERE id<=? ORDER BY id", (end_id,)):
            i, received, source, kind, blob, digest = row
            yield Event(i, received, source, kind, json.loads(zlib.decompress(blob)), digest)

    def verify(self, end_id=None):
        digest = "0" * 64
        n = 0
        for e in self.events(end_id):
            digest = hashlib.sha256(bytes.fromhex(digest) + canonical(
                [e.received_ns, e.source_ns, e.kind, e.payload])).hexdigest()
            if digest != e.digest:
                raise ValueError(f"Event hash mismatch at {e.id}")
            n += 1
        return {"verified_events": n, "sha256_chain": digest}

    def stats(self):
        return {
            "prefix": self.prefix(),
            "bytes": sum(p.stat().st_size for p in self.path.parent.glob(self.path.name + "*") if p.is_file()),
            "streams": [{"kind": r[0], "events": r[1], "first_ns": r[2], "last_ns": r[3]}
                        for r in self.conn.execute("SELECT * FROM counts ORDER BY kind")],
        }

    def backup(self, destination):
        destination = Path(destination)
        if destination.exists():
            raise ValueError('Refusing to overwrite a backup')
        destination.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(destination)
        try:
            self.conn.backup(target, pages=128)
        finally:
            target.close()
        copy = Store(destination, readonly=True)
        try:
            return copy.verify()
        finally:
            copy.close()

    def close(self):
        self.commit()
        self.conn.close()
        if not self.readonly:
            self.lock.close()
