from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
from pathlib import Path

from research_lab.checkpoint import decode, encode
from research_lab.segments import Bucket, archive_events, checksum, durable_json
from research_lab.storage import canonical

from .market_calibration import development_report
from .tape import DecisionTape, TapeConfig

STUDY = "010-011-development"
DATASET = "e2d5cb33e7c44660809b531f03d4b4e3"
START_SEGMENT = 4345
SEED_DIGEST = "cf620d41eb95df0912d1a26ec1708d9545a821dbb3a3442647f09bab8055f786"
TERMINAL_SEGMENT = 7636
TERMINAL_DIGEST = "7700cb0359bef4d775dae80b8fb2c0fb26a29a97332e7b5d2e21bd34bded504b"


def _hash(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def source_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def registration() -> dict:
    config = TapeConfig()
    return {
        "study": STUDY,
        "dataset": DATASET,
        "start_segment": START_SEGMENT,
        "seed_digest": SEED_DIGEST,
        "terminal_segment": TERMINAL_SEGMENT,
        "terminal_digest": TERMINAL_DIGEST,
        "source_sha256": source_hash(),
        "scope": "Read-only Studies 010/011 development; no order-submission path",
        "sample_seconds_left": list(config.sample_seconds_left),
        "maximum_decision_lag_ms": config.maximum_decision_lag_ms,
        "arrival_latency_ms": config.latency_ms,
        "maximum_book_age_ms": config.maximum_book_age_ms,
        "maximum_index_age_ms": config.maximum_index_age_ms,
        "classification": "development_only_not_untouched_validation",
    }


class LocalSettlementResearchRunner:
    """Resumable, hash-linked local extraction for Studies 010 and 011."""

    def __init__(
        self,
        manifest_path,
        seed_path,
        root,
        *,
        checkpoint_every=10,
        keep_archives=False,
        bucket=None,
    ):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.archive_root = self.root / "archives"
        self.archive_root.mkdir(exist_ok=True)
        self.lock = (self.root / "runner.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError("Another local settlement-research runner owns this study") from None
        self.checkpoint_every = max(1, int(checkpoint_every))
        self.keep_archives = keep_archives
        self.bucket = bucket or Bucket()
        self.seed_path = Path(seed_path)
        self.manifest = json.loads(Path(manifest_path).read_text())
        self._validate_manifest()
        self.manifest_sha = _hash(self.manifest)
        self.registration = registration()
        self.registration_sha = _hash(self.registration)
        self.tape, self.next_segment, self.last_digest = self._load()

    def _validate_manifest(self):
        ids = [int(row["id"]) for row in self.manifest]
        if ids != list(range(START_SEGMENT, TERMINAL_SEGMENT + 1)):
            raise ValueError("Settlement-research manifest does not match the frozen range")
        if any(row.get("status") != "archived" for row in self.manifest):
            raise ValueError("Settlement-research manifest contains a non-archived segment")
        if self.manifest[0]["previous_digest"] != SEED_DIGEST:
            raise ValueError("Settlement-research manifest seed linkage mismatch")
        for previous, row in zip(self.manifest, self.manifest[1:]):
            if row["previous_digest"] != previous["digest"]:
                raise ValueError("Settlement-research manifest digest linkage mismatch")
        if self.manifest[-1]["digest"] != TERMINAL_DIGEST:
            raise ValueError("Settlement-research manifest terminal digest mismatch")

    def _load(self):
        local_registration = {**self.registration, "manifest_sha256": self.manifest_sha}
        registration_path = self.root / "registration.json"
        if registration_path.exists():
            if json.loads(registration_path.read_text()) != local_registration:
                raise RuntimeError("Settlement-research registration/source mismatch")
        else:
            durable_json(registration_path, local_registration)
        checkpoint_path = self.root / "checkpoint.json"
        if checkpoint_path.exists():
            envelope = json.loads(checkpoint_path.read_text())
            data = envelope["data"]
            if _hash(data) != envelope["sha256"]:
                raise ValueError("Settlement-research checkpoint checksum mismatch")
            if (
                data["registration_sha256"] != self.registration_sha
                or data["manifest_sha256"] != self.manifest_sha
                or data["dataset"] != DATASET
            ):
                raise RuntimeError("Settlement-research checkpoint identity mismatch")
            return DecisionTape.from_snapshot(decode(data["state"])), data["next_segment"], data["last_digest"]

        envelope = json.loads(self.seed_path.read_text())
        seed_data = envelope["data"]
        if _hash(seed_data) != envelope["sha256"]:
            raise ValueError("Frozen seed checkpoint checksum mismatch")
        if (
            seed_data["dataset"] != DATASET
            or seed_data["next_segment"] != START_SEGMENT
            or seed_data["last_digest"] != SEED_DIGEST
        ):
            raise RuntimeError("Frozen seed identity mismatch")
        replay = decode(seed_data["replay"])
        tape = DecisionTape.from_seed(replay.state, replay.last_ns, replay.last_decision_second)
        self._save(tape, START_SEGMENT, SEED_DIGEST)
        return tape, START_SEGMENT, SEED_DIGEST

    def _save(self, tape, next_segment, last_digest):
        data = {
            "study": STUDY,
            "registration_sha256": self.registration_sha,
            "manifest_sha256": self.manifest_sha,
            "dataset": DATASET,
            "next_segment": next_segment,
            "last_digest": last_digest,
            "state": encode(tape.snapshot()),
        }
        if len(canonical(data)) > 100_000_000:
            raise ValueError("Settlement-research checkpoint capacity reached")
        durable_json(self.root / "checkpoint.json", {"data": data, "sha256": _hash(data)})

    def _archive_path(self, row):
        suffix = ".jsonl.zst" if row["archive_key"].endswith(".zst") else ".jsonl.gz"
        return self.archive_root / f"segment-{int(row['id']):08d}{suffix}"

    def _complete(self):
        if self.last_digest != TERMINAL_DIGEST:
            raise ValueError("Settlement-research terminal digest mismatch")
        tape_report = self.tape.report()
        calibration = development_report(tape_report["rows"])
        envelope = {
            "study": STUDY,
            "registration": self.registration,
            "registration_sha256": self.registration_sha,
            "manifest_sha256": self.manifest_sha,
            "terminal_digest": self.last_digest,
            "development_complete": True,
            "tape": tape_report,
            "market_calibration_study_010": calibration,
            "jump_robust_study_011": {
                "state": "feature_audit_complete_model_not_fitted",
                "coverage": tape_report["coverage"],
                "promotion_authorized": False,
            },
        }
        envelope["report_sha256"] = _hash(envelope)
        durable_json(self.root / "development-report.json", envelope)
        return "development_complete"

    def process_next(self):
        if self.next_segment > TERMINAL_SEGMENT:
            return self._complete()
        row = self.manifest[self.next_segment - START_SEGMENT]
        if row["previous_digest"] != self.last_digest:
            raise ValueError("Settlement-research segment predecessor mismatch")
        path = self._archive_path(row)
        if path.exists() and checksum(path) != row["archive_sha"]:
            path.unlink()
        if not path.exists():
            self.bucket.get(row["archive_key"], path, row["archive_sha"])
        for event in archive_events(path, row):
            self.tape.feed(event)

        completed_segment = int(row["id"])
        self.next_segment = completed_segment + 1
        self.last_digest = row["digest"]
        should_checkpoint = (
            self.next_segment > TERMINAL_SEGMENT
            or (self.next_segment - START_SEGMENT) % self.checkpoint_every == 0
        )
        if should_checkpoint:
            self._save(self.tape, self.next_segment, self.last_digest)
        durable_json(self.root / "latest-status.json", {
            "study": STUDY,
            "state": "processed_segment",
            "last_segment": completed_segment,
            "next_segment": self.next_segment,
            "last_digest": self.last_digest,
            "events_replayed": self.tape.events,
            "rows": len(self.tape.rows),
            "checkpointed": should_checkpoint,
            "updated_ns": time.time_ns(),
        })
        if not self.keep_archives:
            path.unlink()
        return "processed"

    def close(self):
        if not self.lock.closed:
            try:
                self._save(self.tape, self.next_segment, self.last_digest)
            finally:
                self.lock.close()


def default_paths():
    root = Path(os.environ.get("LAB_SETTLEMENT_RESEARCH_ROOT", "data/settlement-research-run"))
    inputs = Path(os.environ.get("LAB_SETTLEMENT_RESEARCH_INPUT", "data/settlement-research-input"))
    return inputs / "manifest.json", inputs / "seed-checkpoint.json", root
