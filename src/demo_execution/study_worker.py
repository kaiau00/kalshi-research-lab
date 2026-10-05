"""Short-lived wrappers around frozen research workers.

The candidate implementation remains unchanged. Running it in a child process
lets Python release its decoded checkpoint and temporary JSON heap after each
batch instead of charging Railway for that memory continuously.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

from research_lab.storage import canonical


def volume_root():
    configured = Path(os.environ.get("LAB_DATA_DIR", "/data"))
    return configured.parent if configured.name == "segments-v6" else configured


def latest_candidate_status():
    path = volume_root() / "candidate-studies" / "003" / "latest-report.json"
    if not path.exists():
        return {"study": "003", "state": "starting"}
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        return {"study": "003", "state": "stale_report_invalid"}


def latest_edge_status():
    path = volume_root() / "edge-validation" / "001" / "latest-report.json"
    if not path.exists():
        return {"study": "edge-validation-001", "state": "not_generated"}
    try:
        report = json.loads(path.read_text())
        expected = report.pop("report_sha256")
        actual = hashlib.sha256(canonical(report)).hexdigest()
        if actual != expected:
            raise ValueError("Edge report checksum mismatch")
        report["report_sha256"] = expected
        return report
    except (OSError, ValueError, TypeError):
        return {"study": "edge-validation-001", "state": "stale_report_invalid"}


def candidate_work_ready():
    status = latest_candidate_status()
    next_segment = status.get("next_segment")
    if next_segment is None:
        return True
    catalog_path = volume_root() / "segments-v6" / "catalog.sqlite3"
    try:
        with sqlite3.connect(catalog_path) as db:
            row = db.execute("SELECT status FROM segments WHERE id=?", (next_segment,)).fetchone()
        return bool(row and row[0] != "open")
    except sqlite3.Error:
        return False


def run_candidate_batch():
    from candidate_study.runner import CandidateRunner
    from edge_validation import EdgeValidationReporter

    runner = CandidateRunner()
    processed = 0
    try:
        while True:
            outcome = runner._process_next()
            if outcome != "complete":
                break
            processed += 1
        edge = EdgeValidationReporter(runner.root)
        edge.refresh()
        return {
            "state": "complete",
            "processed_segments": processed,
            "next_segment": runner.next_segment,
            "outcome": outcome,
        }
    finally:
        runner.close()


def main():
    print(json.dumps(run_candidate_batch(), sort_keys=True))


if __name__ == "__main__":
    main()
