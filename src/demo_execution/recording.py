"""Receipt-ordered segmented recording for the isolated Kalshi demo adapter."""
from __future__ import annotations

import fcntl
import gzip
import hashlib
import os
from pathlib import Path

from research_lab.segments import (
    Bucket,
    SegmentedStore,
    archive_compression_level,
    catalog,
    checksum,
    remove_segment_artifacts,
)
from research_lab.storage import Store, canonical

FORMAT = "demo-segments-v1"


class DemoRecording(SegmentedStore):
    def __init__(self, root, *, strategy, source_sha256):
        super().__init__(root)
        settings = {"format": FORMAT, "strategy": strategy}
        for key, value in settings.items():
            row = self.cat.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            if row and row[0] != value:
                self.close()
                raise RuntimeError("Demo recording registration changed")
            self.cat.execute("INSERT OR IGNORE INTO settings VALUES(?,?)", (key, value))
        self.cat.commit()
        if self.prefix()["last_event_id"] == 0:
            self.append("demo_recording_registration", {
                "dataset": self.dataset,
                "environment": "demo",
                "strategy": strategy,
                "source_sha256": source_sha256,
                "format": FORMAT,
            })
            self.commit()


def archive_one(root, bucket=None):
    """Archive one sealed demo segment only after a full read-back verification."""
    root = Path(root)
    with (root / "processing.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _archive_one(root, bucket)


def _archive_one(root, bucket=None):
    cat = catalog(root)
    output = None
    try:
        row = cat.execute("SELECT * FROM segments WHERE status='sealed' ORDER BY id LIMIT 1").fetchone()
        if row is None:
            return {"state": "idle"}
        row = dict(row)
        dataset = cat.execute("SELECT value FROM settings WHERE key='dataset'").fetchone()[0]
        strategy = cat.execute("SELECT value FROM settings WHERE key='strategy'").fetchone()[0]
        format_row = cat.execute("SELECT value FROM settings WHERE key='format'").fetchone()
        if not format_row or format_row[0] != FORMAT:
            raise RuntimeError("Unknown demo recording format")
        previous = cat.execute("SELECT digest FROM segments WHERE id=?", (row["id"] - 1,)).fetchone()
        expected_previous = previous[0] if previous else "0" * 64
        if row["previous_digest"] != expected_previous:
            raise ValueError("Broken demo segment predecessor")

        source = Store(root / row["path"], readonly=True)
        output = root / f"archive-pending-{row['id']:08d}.jsonl.gz"
        digest = "0" * 64
        count = 0
        try:
            with gzip.open(output, "wb", compresslevel=archive_compression_level()) as stream:
                for event in source.events(row["count"]):
                    digest = hashlib.sha256(bytes.fromhex(digest) + canonical(
                        [event.received_ns, event.source_ns, event.kind, event.payload])).hexdigest()
                    if digest != event.digest:
                        raise ValueError("Demo segment event hash mismatch")
                    if event.id == 1:
                        if row["id"] == 0:
                            expected = {"dataset": dataset, "environment": "demo", "strategy": strategy,
                                        "format": FORMAT}
                            if (event.kind != "demo_recording_registration"
                                    or any(event.payload.get(k) != v for k, v in expected.items())):
                                raise ValueError("Missing demo recording registration")
                        elif (event.kind != "segment_start" or event.payload.get("dataset") != dataset
                              or event.payload.get("segment") != row["id"]
                              or event.payload.get("previous_digest") != row["previous_digest"]):
                            raise ValueError("Broken demo segment linkage")
                    stream.write(canonical([event.id, event.received_ns, event.source_ns, event.kind,
                                            event.payload, event.digest]) + b"\n")
                    count += 1
        finally:
            source.close()
        if count != row["count"] or digest != row["digest"]:
            raise ValueError("Demo segment prefix mismatch")

        used = cat.execute("SELECT COALESCE(SUM(archive_bytes),0) FROM segments").fetchone()[0]
        limit = int(os.environ.get("LAB_DEMO_ARCHIVE_MAX_BYTES", "5000000000"))
        if used + output.stat().st_size > limit:
            raise ValueError("Demo archive budget reached; preserved local segment")
        bucket = bucket or Bucket()
        key = f"demo/{strategy}/{dataset}/segment-{row['id']:08d}-{digest}.jsonl.gz"
        sha = bucket.put_verified(key, output)
        if checksum(output) != sha:
            raise ValueError("Demo archive local checksum changed")
        cat.execute("UPDATE segments SET status='archived',archive_key=?,archive_sha=?,archive_bytes=? WHERE id=?",
                    (key, sha, output.stat().st_size, row["id"]))
        cat.commit()
        remove_segment_artifacts(root / row["path"])
        output.unlink()
        return {"state": "complete", "segment": row["id"], "events": count,
                "digest": digest, "archive_sha256": sha, "archive_key": key}
    finally:
        if output:
            output.unlink(missing_ok=True)
        cat.close()
