#!/usr/bin/env python3
"""Download the frozen Study 029 tape slice and run the deterministic baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hft_research.baseline_replay import (
    BaselineReplay,
    archived_stream,
    load_manifest,
    merge_events,
    write_report,
)
from research_lab.segments import Bucket, checksum


def download(rows: list[dict], root: Path, bucket: Bucket):
    root.mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(rows, start=1):
        path = root / Path(row["archive_key"]).name
        if path.exists() and checksum(path) == row["archive_sha"]:
            continue
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.unlink(missing_ok=True)
        bucket.get(row["archive_key"], temporary, row["archive_sha"])
        temporary.replace(path)
        if index % 10 == 0 or index == len(rows):
            print(f"downloaded {index}/{len(rows)} to {root}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("data/hft-study-029"))
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()
    main_manifest = load_manifest(args.root / "input/main-manifest.json")
    trade_manifest = load_manifest(args.root / "input/trade-manifest.json")
    if not args.skip_download:
        bucket = Bucket()
        download(main_manifest, args.root / "input/main", bucket)
        download(trade_manifest, args.root / "input/trades", bucket)
    if args.download_only:
        return
    print("verified archives; replaying receipt-time merged streams", flush=True)
    replay = BaselineReplay()
    report = replay.consume(
        merge_events(
            archived_stream(args.root / "input/main", main_manifest),
            archived_stream(args.root / "input/trades", trade_manifest),
        )
    )
    report["inputs"] = {
        "main_segments": len(main_manifest),
        "trade_segments": len(trade_manifest),
        "main_first_segment": main_manifest[0]["id"],
        "main_last_segment": main_manifest[-1]["id"],
        "trade_first_segment": trade_manifest[0]["id"],
        "trade_last_segment": trade_manifest[-1]["id"],
    }
    target = args.root / "output/baseline-report.json"
    write_report(target, report)
    print(json.dumps(report, indent=2), flush=True)
    print(f"wrote {target}", flush=True)


if __name__ == "__main__":
    main()
