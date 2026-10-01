from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from research_lab.checkpoint import decode, encode
from research_lab.segments import Bucket, archive_events, catalog, durable_json
from research_lab.storage import Store, canonical

from .engine import (
    ADVERSE_SLIPPAGE,
    CANDIDATES,
    MARKET_BLEND_WEIGHT,
    MAX_BINARY_SPREAD,
    MIN_DEPTH_MULTIPLE,
    TEMPERATURE_COEFFICIENT,
    CandidateEngine,
)

STUDY = "003"
DATASET = "e2d5cb33e7c44660809b531f03d4b4e3"
START_SEGMENT = 4345
SEED_SEGMENT = 4344
SEED_DIGEST = "cf620d41eb95df0912d1a26ec1708d9545a821dbb3a3442647f09bab8055f786"


def source_hash():
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def registration():
    return {
        "study": STUDY,
        "dataset": DATASET,
        "start_segment": START_SEGMENT,
        "seed_segment": SEED_SEGMENT,
        "seed_digest": SEED_DIGEST,
        "source_sha256": source_hash(),
        "scope": "KXBTC15M signal-only simulated accounts; no order submission path",
        "candidates": list(CANDIDATES),
        "shared": {
            "bankroll": "100.00", "risk_per_market": "1.00", "min_edge": 0.04,
            "entry_window_seconds": [5, 300], "latency_ms": 500,
            "attempts": 3, "attempt_spacing_seconds": 10,
        },
        "market_blend": {"market_weight": MARKET_BLEND_WEIGHT, "space": "log_odds"},
        "calibration": {
            "method": "symmetric_temperature_scaling", "coefficient": TEMPERATURE_COEFFICIENT,
            "fit_trades": 616, "l2_penalty_around_one": 1,
            "baseline_log_loss": 0.5148963080793826,
            "calibrated_log_loss": 0.5039266910399527,
        },
        "guards": {
            "max_binary_spread": str(MAX_BINARY_SPREAD),
            "adverse_slippage": str(ADVERSE_SLIPPAGE),
            "min_depth_multiple": MIN_DEPTH_MULTIPLE,
            "persistence_seconds": 2, "max_ask_change": "0.01",
        },
        "review_gate": {"minimum_utc_dates": 20, "minimum_settled_markets_per_candidate": 100},
    }


def _sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _compact_results(results):
    accounts = {}
    for name, values in results["accounts"].items():
        accounts[name] = {key: value for key, value in values.items()
                          if key not in ("orders", "closed_trades", "decisions", "equity")}
    return {key: value for key, value in results.items() if key != "accounts"} | {"accounts": accounts}


class CandidateRunner:
    def __init__(self):
        configured_root = Path(os.environ.get("LAB_DATA_DIR", "/data"))
        if configured_root.name == "segments-v6":
            volume_root, self.segment_root = configured_root.parent, configured_root
        else:
            volume_root, self.segment_root = configured_root, configured_root / "segments-v6"
        self.root = volume_root / "candidate-studies" / STUDY
        self.seed_path = volume_root / "comparisons" / "v6-002" / "checkpoint.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = (self.root / "runner.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError("Another candidate study runner owns this study") from None
        self.registration = registration()
        self.registration_sha = _sha(self.registration)
        self.engine, self.next_segment, self.last_digest = self._load()
        self.processed_segments = self.next_segment - START_SEGMENT
        self.status = self._status("starting")

    def _load(self):
        registration_path = self.root / "registration.json"
        if registration_path.exists():
            if json.loads(registration_path.read_text()) != self.registration:
                raise RuntimeError("Candidate study registration/source mismatch")
        else:
            durable_json(registration_path, self.registration)
        checkpoint = self.root / "checkpoint.json"
        if checkpoint.exists():
            envelope = json.loads(checkpoint.read_text())
            data = envelope["data"]
            if _sha(data) != envelope["sha256"]:
                raise ValueError("Candidate checkpoint checksum mismatch")
            if (data["registration_sha256"] != self.registration_sha or data["dataset"] != DATASET
                    or data["next_segment"] < START_SEGMENT):
                raise RuntimeError("Candidate checkpoint registration/dataset mismatch")
            saved = decode(data["state"])
            return CandidateEngine(saved["replay"], saved["guard_quotes"]), data["next_segment"], data["last_digest"]
        envelope = json.loads(self.seed_path.read_text())
        seed_data = envelope["data"]
        if _sha(seed_data) != envelope["sha256"]:
            raise ValueError("Frozen seed checkpoint checksum mismatch")
        if (seed_data["dataset"] != DATASET or seed_data["next_segment"] != START_SEGMENT
                or seed_data["last_digest"] != SEED_DIGEST):
            raise RuntimeError("Frozen seed identity mismatch")
        seed = decode(seed_data["replay"])
        engine = CandidateEngine.from_seed(seed)
        self._save(engine, START_SEGMENT, SEED_DIGEST)
        return engine, START_SEGMENT, SEED_DIGEST

    def _save(self, engine, next_segment, last_digest):
        data = {
            "study": STUDY, "registration_sha256": self.registration_sha,
            "dataset": DATASET, "next_segment": next_segment, "last_digest": last_digest,
            "state": encode({"replay": engine.replay, "guard_quotes": engine.guard_quotes}),
        }
        if len(canonical(data)) > 100_000_000:
            raise ValueError("Candidate checkpoint capacity reached")
        durable_json(self.root / "checkpoint.json", {"data": data, "sha256": _sha(data)})

    def _status(self, state, **extra):
        results = _compact_results(self.engine.results())
        dates = sorted({day for account in results["accounts"].values()
                        for day in account["daily_pnl"]})
        return {
            "study": STUDY, "state": state, "source_sha256": self.registration["source_sha256"],
            "registration_sha256": self.registration_sha, "dataset": DATASET,
            "start_segment": START_SEGMENT, "next_segment": self.next_segment,
            "processed_segments": self.processed_segments, "forward_utc_dates": dates,
            "results": results, "updated_ns": time.time_ns(), **extra,
        }

    def _process_next(self):
        processing_lock = None
        cat = catalog(self.segment_root)
        try:
            dataset = cat.execute("SELECT value FROM settings WHERE key='dataset'").fetchone()[0]
            if dataset != DATASET:
                raise RuntimeError("Candidate source dataset mismatch")
            row = cat.execute("SELECT * FROM segments WHERE id=?", (self.next_segment,)).fetchone()
            if row is None or row["status"] == "open":
                return "idle"
            row = dict(row)
            if row["status"] == "sealed":
                cat.close()
                cat = None
                processing_lock = (self.segment_root / "processing.lock").open("a")
                try:
                    fcntl.flock(processing_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return "busy"
                cat = catalog(self.segment_root)
                fresh = cat.execute("SELECT * FROM segments WHERE id=?", (self.next_segment,)).fetchone()
                if fresh is None or fresh["status"] == "open":
                    return "idle"
                row = dict(fresh)
            if row["previous_digest"] != self.last_digest:
                raise ValueError("Candidate segment predecessor mismatch")
            source = None
            temp_path = None
            if row["status"] == "sealed":
                source = Store(self.segment_root / row["path"], readonly=True)
                events = source.events(row["count"])
            elif row["status"] == "archived":
                fd, name = tempfile.mkstemp(prefix=f"candidate-{row['id']}-", suffix=".jsonl.gz",
                                            dir=self.root)
                os.close(fd)
                temp_path = Path(name)
                Bucket().get(row["archive_key"], temp_path, row["archive_sha"])
                events = archive_events(temp_path, row)
            else:
                raise ValueError("Unknown segment status")
            count = 0
            digest = "0" * 64
            try:
                for event in events:
                    if count == 0 and (event.kind != "segment_start"
                            or event.payload.get("dataset") != DATASET
                            or event.payload.get("previous_digest") != self.last_digest):
                        raise ValueError("Broken candidate segment linkage")
                    digest = hashlib.sha256(bytes.fromhex(digest) + canonical(
                        [event.received_ns, event.source_ns, event.kind, event.payload])).hexdigest()
                    if event.digest and digest != event.digest:
                        raise ValueError("Candidate segment event hash mismatch")
                    self.engine.feed(event)
                    count += 1
                if count != row["count"] or digest != row["digest"]:
                    raise ValueError("Candidate segment prefix mismatch")
            finally:
                if source:
                    source.close()
                if temp_path:
                    temp_path.unlink(missing_ok=True)
            self.next_segment = row["id"] + 1
            self.last_digest = digest
            self.processed_segments = self.next_segment - START_SEGMENT
            self._save(self.engine, self.next_segment, self.last_digest)
            report = self._status("caught_up_through_segment", last_segment=row["id"])
            durable_json(self.root / "latest-report.json", report)
            return "complete"
        finally:
            if cat:
                cat.close()
            if processing_lock:
                processing_lock.close()

    async def run(self):
        while True:
            try:
                outcome = await asyncio.to_thread(self._process_next)
                state = {"complete": "catching_up", "idle": "waiting_for_segment",
                         "busy": "waiting_for_archiver"}[outcome]
                self.status = self._status(state)
                await asyncio.sleep(0 if outcome == "complete" else 1)
            except asyncio.CancelledError:
                raise
            except (ValueError, RuntimeError) as exc:
                self.status = self._status("stopped_error", error=str(exc))
                durable_json(self.root / "last-error.json", self.status)
                return
            except Exception as exc:
                self.status = self._status("waiting_io", error=f"{type(exc).__name__}: {exc}")
                await asyncio.sleep(5)

    def close(self):
        if not self.lock.closed:
            self.lock.close()
