#!/usr/bin/env python3
"""Download a bounded archive manifest and build a verified Rollover Bridge tape."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research_lab.research import write_json
from research_lab.segments import Bucket, archive_events
from rollover_bridge.tape import DecisionTape


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("archive_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()

    rows = json.loads(args.manifest.read_text())
    if not rows or any(row.get("status") != "archived" for row in rows):
        raise ValueError("Manifest must contain archived segments")
    ids = [int(row["id"]) for row in rows]
    if ids != list(range(ids[0], ids[-1] + 1)):
        raise ValueError("Manifest segments must be consecutive")
    for previous, row in zip(rows, rows[1:]):
        if row["previous_digest"] != previous["digest"]:
            raise ValueError("Manifest digest linkage mismatch")

    args.archive_dir.mkdir(parents=True, exist_ok=True)
    bucket = Bucket() if args.download else None
    tape = DecisionTape()
    for row in rows:
        suffix = ".jsonl.zst" if row["archive_key"].endswith(".zst") else ".jsonl.gz"
        path = args.archive_dir / f"segment-{int(row['id']):08d}{suffix}"
        if not path.exists():
            if bucket is None:
                raise FileNotFoundError(path)
            bucket.get(row["archive_key"], path, row["archive_sha"])
        for event in archive_events(path, row):
            tape.feed(event)

    report = tape.report()
    report["manifest"] = {
        "first_segment": ids[0],
        "last_segment": ids[-1],
        "first_previous_digest": rows[0]["previous_digest"],
        "last_digest": rows[-1]["digest"],
        "verified_archives": len(rows),
        "development_only": True,
    }
    write_json(args.output, report)
    print(json.dumps({
        "output": str(args.output),
        "events_replayed": report["events_replayed"],
        "coverage": report["coverage"],
        "quality": report["quality"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
