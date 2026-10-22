"""Verified, bounded archive path for the Study 028 public-trade tape."""

from __future__ import annotations

import fcntl
import hashlib
import os
import time
from pathlib import Path

from research_lab.segments import (
    Bucket,
    archive_suffix,
    archive_writer,
    catalog,
    checksum,
    durable_json,
    remove_segment_artifacts,
)
from research_lab.storage import Store, canonical

from .provenance import TRADE_TAPE_FORMAT


def process_trade_segment(root, bucket=None):
    """Archive one sealed segment and preserve it locally on every failure."""

    root = Path(root)
    with (root / "processing.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _process_trade_segment(root, bucket)


def _setting(cat, key):
    row = cat.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if row is None:
        raise ValueError(f"Missing trade-tape setting: {key}")
    return row[0]


def _manifest(cat, dataset, candidate):
    segments = []
    for existing in cat.execute("SELECT * FROM segments WHERE status='archived' ORDER BY id"):
        segments.append({
            "id": existing["id"],
            "events": existing["count"],
            "digest": existing["digest"],
            "previous_digest": existing["previous_digest"],
            "archive_key": existing["archive_key"],
            "archive_sha256": existing["archive_sha"],
            "archive_bytes": existing["archive_bytes"],
        })
    segments.append(candidate)
    return {
        "format": TRADE_TAPE_FORMAT,
        "dataset": dataset,
        "study_registration_sha256": _setting(cat, "study_registration_sha256"),
        "source_sha256": _setting(cat, "source_sha256"),
        "generated_ns": time.time_ns(),
        "segments": segments,
    }


def _process_trade_segment(root, bucket=None):
    cat = catalog(root)
    output = manifest_path = None
    try:
        row = cat.execute("SELECT * FROM segments WHERE status='sealed' ORDER BY id LIMIT 1").fetchone()
        if row is None:
            return {"state": "idle"}
        row = dict(row)
        dataset = _setting(cat, "dataset")
        if _setting(cat, "format") != TRADE_TAPE_FORMAT:
            raise ValueError("Unknown trade-tape format")
        study_hash = _setting(cat, "study_registration_sha256")
        source_hash = _setting(cat, "source_sha256")
        previous = cat.execute("SELECT digest FROM segments WHERE id=?", (row["id"] - 1,)).fetchone()
        expected_previous = previous[0] if previous else "0" * 64
        if row["previous_digest"] != expected_previous:
            raise ValueError("Broken trade-tape segment predecessor")

        source = Store(root / row["path"], readonly=True)
        output = root / f"archive-pending-{row['id']:08d}{archive_suffix()}"
        digest = "0" * 64
        count = 0
        try:
            with archive_writer(output) as stream:
                for event in source.events(row["count"]):
                    digest = hashlib.sha256(bytes.fromhex(digest) + canonical(
                        [event.received_ns, event.source_ns, event.kind, event.payload]
                    )).hexdigest()
                    if digest != event.digest:
                        raise ValueError("Trade-tape event hash mismatch")
                    if event.id == 1:
                        if row["id"] == 0:
                            expected = {
                                "dataset": dataset,
                                "format": TRADE_TAPE_FORMAT,
                                "series": "KXBTC15M",
                                "channel": "trade",
                                "study_registration_sha256": study_hash,
                                "source_sha256": source_hash,
                                "production_orders_authorized": False,
                                "demo_orders_authorized": False,
                            }
                            if (event.kind != "hft_trade_registration"
                                    or any(event.payload.get(k) != v for k, v in expected.items())):
                                raise ValueError("Missing matching trade-tape registration")
                        elif (event.kind != "segment_start"
                              or event.payload.get("dataset") != dataset
                              or event.payload.get("segment") != row["id"]
                              or event.payload.get("previous_digest") != row["previous_digest"]):
                            raise ValueError("Broken trade-tape segment linkage")
                    stream.write(canonical([
                        event.id,
                        event.received_ns,
                        event.source_ns,
                        event.kind,
                        event.payload,
                        event.digest,
                    ]) + b"\n")
                    count += 1
        finally:
            source.close()
        if count != row["count"] or digest != row["digest"]:
            raise ValueError("Trade-tape segment prefix mismatch")

        used = cat.execute("SELECT COALESCE(SUM(archive_bytes),0) FROM segments").fetchone()[0]
        limit = int(os.environ.get("LAB_HFT_TRADE_ARCHIVE_MAX_BYTES", "5000000000"))
        if used + output.stat().st_size > limit:
            raise ValueError("HFT trade archive budget reached; preserved local segment")

        bucket = bucket or Bucket()
        prefix = f"hft-trades-v1/{dataset}"
        key = f"{prefix}/segment-{row['id']:08d}-{digest}{archive_suffix()}"
        sha = bucket.put_verified(key, output)
        if checksum(output) != sha:
            raise ValueError("Trade-tape archive local checksum changed")

        candidate = {
            "id": row["id"],
            "events": count,
            "digest": digest,
            "previous_digest": row["previous_digest"],
            "archive_key": key,
            "archive_sha256": sha,
            "archive_bytes": output.stat().st_size,
        }
        manifest_path = root / "manifest.json"
        durable_json(manifest_path, _manifest(cat, dataset, candidate))
        manifest_sha = bucket.put_verified(f"{prefix}/manifest.json", manifest_path)

        cat.execute(
            "UPDATE segments SET status='archived',archive_key=?,archive_sha=?,archive_bytes=? WHERE id=?",
            (key, sha, output.stat().st_size, row["id"]),
        )
        cat.commit()
        remove_segment_artifacts(root / row["path"])
        output.unlink()
        return {
            "state": "complete",
            "segment": row["id"],
            "events": count,
            "digest": digest,
            "archive_sha256": sha,
            "archive_key": key,
            "manifest_sha256": manifest_sha,
        }
    finally:
        if output:
            output.unlink(missing_ok=True)
        cat.close()
