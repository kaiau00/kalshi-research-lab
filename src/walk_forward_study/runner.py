from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from candidate_study.engine import TEMPERATURE_COEFFICIENT
from research_lab.checkpoint import decode, encode
from research_lab.segments import Bucket, archive_events, catalog, durable_json
from research_lab.storage import Store, canonical

from .engine import CONFIGS, REFERENCE, WalkForwardEngine

STUDY = "004"
DATASET = "e2d5cb33e7c44660809b531f03d4b4e3"
START_SEGMENT = 0
END_SEGMENT = 4344
TERMINAL_DIGEST = "cf620d41eb95df0912d1a26ec1708d9545a821dbb3a3442647f09bab8055f786"
ZERO_DIGEST = "0" * 64
CHECKPOINT_INTERVAL = 25


def source_hash():
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def registration():
    return {
        "study": STUDY, "dataset": DATASET, "start_segment": START_SEGMENT,
        "end_segment": END_SEGMENT, "terminal_digest": TERMINAL_DIGEST,
        "source_sha256": source_hash(),
        "scope": "KXBTC15M development-only simulated parameter study; no order submission path",
        "shared": {"bankroll": "100.00", "risk_per_market": "1.00", "latency_ms": 500,
                   "attempts": 3, "attempt_spacing_seconds": 10,
                   "execution": "delayed_ioc", "official_outcomes_only": True},
        "calibration_coefficient": TEMPERATURE_COEFFICIENT,
        "configurations": list(CONFIGS), "reference": REFERENCE,
        "volatility_regimes_fast_rms_bps": {"low": "<0.5", "medium": "0.5-1.5", "high": ">1.5"},
        "blocks": 5, "checkpoint_interval_segments": CHECKPOINT_INTERVAL,
        "promotion_gates": {"minimum_settlements": 100, "positive_pnl": True,
                            "positive_without_top_three": True, "positive_two_cent_stress": True,
                            "minimum_positive_blocks": 4, "positive_day_share_above": 0.5,
                            "maximum_drawdown": 20, "log_loss_no_worse_than_reference": True},
        "development_only": True, "requires_new_prospective_study": True,
    }


def _sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


class ParameterRunner:
    def __init__(self):
        configured_root = Path(os.environ.get("LAB_DATA_DIR", "/data"))
        if configured_root.name == "segments-v6":
            volume_root, self.segment_root = configured_root.parent, configured_root
        else:
            volume_root, self.segment_root = configured_root, configured_root / "segments-v6"
        self.root = volume_root / "parameter-studies" / STUDY
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = (self.root / "runner.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError("Another parameter study runner owns this study") from None
        self.registration = registration()
        self.registration_sha = _sha(self.registration)
        self.engine, self.next_segment, self.last_digest = self._load()
        self.latest_results = None
        report = self.root / "latest-report.json"
        if report.exists():
            self.latest_results = json.loads(report.read_text()).get("results")
        self.status = self._status("starting")

    def _load(self):
        path = self.root / "registration.json"
        if path.exists():
            if json.loads(path.read_text()) != self.registration:
                raise RuntimeError("Parameter study registration/source mismatch")
        else:
            durable_json(path, self.registration)
        checkpoint = self.root / "checkpoint.json"
        if not checkpoint.exists():
            engine = WalkForwardEngine()
            self._save(engine, START_SEGMENT, ZERO_DIGEST)
            return engine, START_SEGMENT, ZERO_DIGEST
        envelope = json.loads(checkpoint.read_text())
        data = envelope["data"]
        if _sha(data) != envelope["sha256"]:
            raise ValueError("Parameter study checkpoint checksum mismatch")
        if (data["registration_sha256"] != self.registration_sha or data["dataset"] != DATASET
                or not START_SEGMENT <= data["next_segment"] <= END_SEGMENT + 1):
            raise RuntimeError("Parameter study checkpoint registration/dataset mismatch")
        return WalkForwardEngine.from_state(decode(data["state"])), data["next_segment"], data["last_digest"]

    def _save(self, engine, next_segment, last_digest):
        data = {"study": STUDY, "registration_sha256": self.registration_sha,
                "dataset": DATASET, "next_segment": next_segment, "last_digest": last_digest,
                "state": encode(engine.state())}
        if len(canonical(data)) > 150_000_000:
            raise ValueError("Parameter study checkpoint capacity reached")
        durable_json(self.root / "checkpoint.json", {"data": data, "sha256": _sha(data)})

    def _status(self, state, **extra):
        return {"study": STUDY, "state": state, "source_sha256": self.registration["source_sha256"],
                "registration_sha256": self.registration_sha, "dataset": DATASET,
                "start_segment": START_SEGMENT, "end_segment": END_SEGMENT,
                "next_segment": self.next_segment, "processed_segments": self.next_segment,
                "progress": self.next_segment / (END_SEGMENT + 1), "configuration_count": len(CONFIGS),
                "results": self.latest_results, "updated_ns": time.time_ns(), **extra}

    def _report(self, state):
        self.latest_results = self.engine.results()
        report = self._status(state)
        durable_json(self.root / "latest-report.json", report)
        return report

    def _process_next(self):
        if self.next_segment > END_SEGMENT:
            return "finished"
        cat = catalog(self.segment_root)
        source = None
        temp_path = None
        try:
            dataset = cat.execute("SELECT value FROM settings WHERE key='dataset'").fetchone()[0]
            if dataset != DATASET:
                raise RuntimeError("Parameter study source dataset mismatch")
            row = cat.execute("SELECT * FROM segments WHERE id=?", (self.next_segment,)).fetchone()
            if row is None or row["status"] == "open":
                return "missing"
            row = dict(row)
            if row["previous_digest"] != self.last_digest:
                raise ValueError("Parameter study segment predecessor mismatch")
            if row["status"] == "archived":
                fd, name = tempfile.mkstemp(prefix=f"parameter-{row['id']}-", suffix=".jsonl.gz",
                                            dir=self.root)
                os.close(fd)
                temp_path = Path(name)
                Bucket().get(row["archive_key"], temp_path, row["archive_sha"])
                events = archive_events(temp_path, row)
            elif row["status"] == "sealed":
                source = Store(self.segment_root / row["path"], readonly=True)
                events = source.events(row["count"])
            else:
                raise ValueError("Unknown parameter segment status")
            digest = ZERO_DIGEST
            count = 0
            for event in events:
                if count == 0:
                    if row["id"] == 0 and event.kind != "experiment_registration":
                        raise ValueError("Missing initial experiment registration")
                    if row["id"] > 0 and (event.kind != "segment_start"
                            or event.payload.get("dataset") != DATASET
                            or event.payload.get("previous_digest") != self.last_digest):
                        raise ValueError("Broken parameter segment linkage")
                digest = hashlib.sha256(bytes.fromhex(digest) + canonical(
                    [event.received_ns, event.source_ns, event.kind, event.payload])).hexdigest()
                if event.digest and digest != event.digest:
                    raise ValueError("Parameter segment event hash mismatch")
                self.engine.feed(event)
                count += 1
            if count != row["count"] or digest != row["digest"]:
                raise ValueError("Parameter segment prefix mismatch")
            self.next_segment = row["id"] + 1
            self.last_digest = digest
            if self.next_segment % CHECKPOINT_INTERVAL == 0 or self.next_segment == END_SEGMENT + 1:
                if self.next_segment == END_SEGMENT + 1 and digest != TERMINAL_DIGEST:
                    raise ValueError("Parameter study terminal digest mismatch")
                self._save(self.engine, self.next_segment, self.last_digest)
                self._report("complete" if self.next_segment == END_SEGMENT + 1 else "checkpointed")
            return "finished" if self.next_segment == END_SEGMENT + 1 else "complete"
        finally:
            cat.close()
            if source:
                source.close()
            if temp_path:
                temp_path.unlink(missing_ok=True)

    async def run(self):
        while True:
            try:
                outcome = await asyncio.to_thread(self._process_next)
                if outcome == "finished":
                    if self.next_segment == END_SEGMENT + 1 and self.latest_results is None:
                        self._report("complete")
                    self.status = self._status("complete")
                    return
                self.status = self._status("running" if outcome == "complete" else "waiting_for_prefix")
                await asyncio.sleep(0 if outcome == "complete" else 5)
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
