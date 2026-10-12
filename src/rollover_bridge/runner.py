from __future__ import annotations

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

from .features import HISTORY_SECONDS, PRIOR_MINUTE_SECONDS, VELOCITY_HALF_LIFE_SECONDS
from .tape import DecisionTape, TapeConfig

STUDY = "007-development"
DATASET = "e2d5cb33e7c44660809b531f03d4b4e3"
START_SEGMENT = 4345
SEED_DIGEST = "cf620d41eb95df0912d1a26ec1708d9545a821dbb3a3442647f09bab8055f786"
TERMINAL_SEGMENT = 7540
TERMINAL_DIGEST = "aab571dfb5ee829b2fe3f00a06af8ce0cd7d7494e4319ff563e7848b4f44aab4"


def source_hash():
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def registration():
    config = TapeConfig()
    return {
        "study": STUDY,
        "dataset": DATASET,
        "start_segment": START_SEGMENT,
        "seed_digest": SEED_DIGEST,
        "terminal_segment": TERMINAL_SEGMENT,
        "terminal_digest": TERMINAL_DIGEST,
        "source_sha256": source_hash(),
        "scope": "Read-only development decision tape; no order-submission path",
        "sampling": {
            "offsets_after_open_seconds": list(config.sample_offsets_seconds),
            "maximum_decision_lag_ms": config.maximum_decision_lag_ms,
            "arrival_latency_ms": config.latency_ms,
            "maximum_book_age_ms": config.maximum_book_age_ms,
        },
        "forecast": {
            "history_seconds": HISTORY_SECONDS,
            "prior_minute_seconds": PRIOR_MINUTE_SECONDS,
            "velocity_half_life_seconds": VELOCITY_HALF_LIFE_SECONDS,
            "continuous_variance": "bipower_variation",
            "jump_variance": "positive_realized_minus_bipower_variation",
        },
        "classification": "development_only_not_untouched_validation",
    }


def _hash(value):
    return hashlib.sha256(canonical(value)).hexdigest()


class RolloverRunner:
    def __init__(self):
        configured_root = Path(os.environ.get("LAB_DATA_DIR", "/data"))
        if configured_root.name == "segments-v6":
            volume_root, self.segment_root = configured_root.parent, configured_root
        else:
            volume_root, self.segment_root = configured_root, configured_root / "segments-v6"
        self.root = volume_root / "rollover-studies" / STUDY
        self.seed_path = volume_root / "comparisons" / "v6-002" / "checkpoint.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = (self.root / "runner.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError("Another Rollover Bridge runner owns this study") from None
        self.registration = registration()
        self.registration_sha = _hash(self.registration)
        self.tape, self.next_segment, self.last_digest = self._load()

    def _load(self):
        registration_path = self.root / "registration.json"
        if registration_path.exists():
            if json.loads(registration_path.read_text()) != self.registration:
                raise RuntimeError("Rollover study registration/source mismatch")
        else:
            durable_json(registration_path, self.registration)
        checkpoint_path = self.root / "checkpoint.json"
        if checkpoint_path.exists():
            envelope = json.loads(checkpoint_path.read_text())
            data = envelope["data"]
            if _hash(data) != envelope["sha256"]:
                raise ValueError("Rollover checkpoint checksum mismatch")
            if data["registration_sha256"] != self.registration_sha or data["dataset"] != DATASET:
                raise RuntimeError("Rollover checkpoint registration/dataset mismatch")
            return DecisionTape.from_snapshot(decode(data["state"])), data["next_segment"], data["last_digest"]

        envelope = json.loads(self.seed_path.read_text())
        seed_data = envelope["data"]
        if _hash(seed_data) != envelope["sha256"]:
            raise ValueError("Frozen seed checkpoint checksum mismatch")
        if (seed_data["dataset"] != DATASET or seed_data["next_segment"] != START_SEGMENT
                or seed_data["last_digest"] != SEED_DIGEST):
            raise RuntimeError("Frozen seed identity mismatch")
        replay = decode(seed_data["replay"])
        tape = DecisionTape.from_seed(replay.state, replay.last_ns, replay.last_decision_second)
        self._save(tape, START_SEGMENT, SEED_DIGEST)
        return tape, START_SEGMENT, SEED_DIGEST

    def _save(self, tape, next_segment, last_digest):
        data = {
            "study": STUDY,
            "registration_sha256": self.registration_sha,
            "dataset": DATASET,
            "next_segment": next_segment,
            "last_digest": last_digest,
            "state": encode(tape.snapshot()),
        }
        if len(canonical(data)) > 50_000_000:
            raise ValueError("Rollover checkpoint capacity reached")
        durable_json(self.root / "checkpoint.json", {"data": data, "sha256": _hash(data)})

    def _status(self, state, **extra):
        report = self.tape.report()
        report.pop("rows")
        return {
            "study": STUDY,
            "state": state,
            "registration_sha256": self.registration_sha,
            "source_sha256": self.registration["source_sha256"],
            "dataset": DATASET,
            "next_segment": self.next_segment,
            "last_digest": self.last_digest,
            "report": report,
            "updated_ns": time.time_ns(),
            **extra,
        }

    def process_next(self):
        if self.next_segment > TERMINAL_SEGMENT:
            if self.last_digest != TERMINAL_DIGEST:
                raise ValueError("Rollover terminal digest mismatch")
            report = self.tape.report()
            report["registration"] = self.registration
            report["registration_sha256"] = self.registration_sha
            report["terminal_digest"] = self.last_digest
            report["development_complete"] = True
            report["report_sha256"] = _hash(report)
            durable_json(self.root / "development-report.json", report)
            durable_json(self.root / "latest-status.json", self._status("development_complete"))
            return "development_complete"

        processing_lock = None
        cat = catalog(self.segment_root)
        try:
            dataset = cat.execute("SELECT value FROM settings WHERE key='dataset'").fetchone()[0]
            if dataset != DATASET:
                raise RuntimeError("Rollover source dataset mismatch")
            record = cat.execute("SELECT * FROM segments WHERE id=?", (self.next_segment,)).fetchone()
            if record is None or record["status"] == "open":
                return "idle"
            row = dict(record)
            if row["status"] == "sealed":
                cat.close()
                cat = None
                processing_lock = (self.segment_root / "processing.lock").open("a")
                try:
                    fcntl.flock(processing_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return "busy"
                cat = catalog(self.segment_root)
                record = cat.execute("SELECT * FROM segments WHERE id=?", (self.next_segment,)).fetchone()
                if record is None or record["status"] == "open":
                    return "idle"
                row = dict(record)
            if row["previous_digest"] != self.last_digest:
                raise ValueError("Rollover segment predecessor mismatch")

            source = None
            temporary = None
            if row["status"] == "sealed":
                source = Store(self.segment_root / row["path"], readonly=True)
                events = source.events(row["count"])
            elif row["status"] == "archived":
                file_descriptor, name = tempfile.mkstemp(
                    prefix=f"rollover-{row['id']}-", suffix=".archive", dir=self.root)
                os.close(file_descriptor)
                temporary = Path(name)
                Bucket().get(row["archive_key"], temporary, row["archive_sha"])
                events = archive_events(temporary, row)
            else:
                raise ValueError("Unknown segment status")
            try:
                for event in events:
                    self.tape.feed(event)
            finally:
                if source:
                    source.close()
                if temporary:
                    temporary.unlink(missing_ok=True)

            self.next_segment = row["id"] + 1
            self.last_digest = row["digest"]
            self._save(self.tape, self.next_segment, self.last_digest)
            status = self._status("processed_segment", last_segment=row["id"])
            durable_json(self.root / "latest-status.json", status)
            return "processed"
        finally:
            if cat:
                cat.close()
            if processing_lock:
                processing_lock.close()

    def close(self):
        if not self.lock.closed:
            self.lock.close()
