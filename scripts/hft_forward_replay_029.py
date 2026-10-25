#!/usr/bin/env python3
"""Run the frozen HFT baseline over a bounded, synchronized forward-tape slice.

This is an exploratory data-quality and feasibility tool.  It never writes to
Kalshi and labels every report with its selected time interval so a short,
already-viewed slice cannot be mistaken for the preregistered 20-date study.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from hft_research.baseline_replay import BaselineReplay, archived_stream, merge_events, write_report
from research_lab.segments import Bucket, checksum


def parse_time(value: str) -> int:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected ISO-8601 time") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("time must include a timezone")
    return int(parsed.astimezone(UTC).timestamp() * 1_000_000_000)


def segment_bounds(stats: str) -> tuple[int, int]:
    value = json.loads(stats)
    bounds = [
        (stream.get("first_ns"), stream.get("last_ns"))
        for stream in value.get("streams", [])
        if stream.get("first_ns") is not None and stream.get("last_ns") is not None
    ]
    if not bounds:
        raise ValueError("Archived segment has no recorded time bounds")
    return min(first for first, _ in bounds), max(last for _, last in bounds)


def select_segments(catalog_path: Path, start_ns: int, end_ns: int) -> list[dict]:
    """Return verified archived segments whose observed receipt range overlaps the slice."""
    if end_ns <= start_ns:
        raise ValueError("end must be after start")
    database = sqlite3.connect(catalog_path)
    database.row_factory = sqlite3.Row
    try:
        rows = database.execute(
            """SELECT id, count, digest, previous_digest, stats, archive_key, archive_sha, archive_bytes
               FROM segments WHERE status='archived' ORDER BY id"""
        )
        selected = []
        for row in rows:
            first_ns, last_ns = segment_bounds(row["stats"])
            if last_ns < start_ns or first_ns > end_ns:
                continue
            if not row["archive_key"] or not row["archive_sha"]:
                raise ValueError("Archived segment is missing its verified bucket identity")
            selected.append(
                {
                    "id": row["id"],
                    "count": row["count"],
                    "digest": row["digest"],
                    "previous_digest": row["previous_digest"],
                    "archive_key": row["archive_key"],
                    "archive_sha": row["archive_sha"],
                    "archive_bytes": row["archive_bytes"],
                    "first_ns": first_ns,
                    "last_ns": last_ns,
                }
            )
        return selected
    finally:
        database.close()


def download(rows: list[dict], root: Path, bucket: Bucket) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(rows, start=1):
        path = root / Path(row["archive_key"]).name
        if not path.exists() or checksum(path) != row["archive_sha"]:
            temporary = path.with_suffix(path.suffix + ".part")
            temporary.unlink(missing_ok=True)
            bucket.get(row["archive_key"], temporary, row["archive_sha"])
            temporary.replace(path)
        print(f"verified {index}/{len(rows)} {path.name}", flush=True)


def required_archive_bytes(*streams: list[dict]) -> int:
    """Return the compressed download size before any bucket read occurs."""
    return sum(int(row["archive_bytes"]) for rows in streams for row in rows)


def bounded_events(root: Path, manifest: list[dict], start_ns: int, end_ns: int):
    for event in archived_stream(root, manifest):
        if start_ns <= event.received_ns <= end_ns:
            yield event


def selection_metadata(name: str, rows: list[dict]) -> dict:
    return {
        "stream": name,
        "segments": len(rows),
        "archive_bytes": sum(int(row["archive_bytes"]) for row in rows),
        "first_receipt_ns": min((row["first_ns"] for row in rows), default=None),
        "last_receipt_ns": max((row["last_ns"] for row in rows), default=None),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-catalog", type=Path, required=True)
    parser.add_argument("--trade-catalog", type=Path, required=True)
    parser.add_argument("--start", type=parse_time, required=True)
    parser.add_argument("--end", type=parse_time, required=True)
    parser.add_argument("--root", type=Path, default=Path("data/hft-forward-replay-029"))
    parser.add_argument(
        "--max-download-bytes",
        type=int,
        default=100 * 1024 * 1024,
        help="refuse a selection whose compressed archive input exceeds this cap (default: 100 MiB)",
    )
    parser.add_argument("--download-only", action="store_true")
    args = parser.parse_args()

    main_rows = select_segments(args.main_catalog, args.start, args.end)
    trade_rows = select_segments(args.trade_catalog, args.start, args.end)
    if not main_rows or not trade_rows:
        raise SystemExit("Selected interval has no complete main or public-trade segments")
    required_bytes = required_archive_bytes(main_rows, trade_rows)
    if args.max_download_bytes < 0:
        raise SystemExit("--max-download-bytes must be nonnegative")
    if required_bytes > args.max_download_bytes:
        raise SystemExit(
            f"Selected input is {required_bytes} bytes, above --max-download-bytes={args.max_download_bytes}; "
            "choose a shorter interval or explicitly raise the bounded replay cap"
        )
    selection = {
        "study": "029",
        "classification": "exploratory bounded forward-tape replay; not a promotion study",
        "requested_start_ns": args.start,
        "requested_end_ns": args.end,
        "required_archive_bytes": required_bytes,
        "max_download_bytes": args.max_download_bytes,
        "main": selection_metadata("main", main_rows),
        "trade": selection_metadata("trade", trade_rows),
    }
    output = args.root / "output"
    output.mkdir(parents=True, exist_ok=True)
    (output / "selection.json").write_text(json.dumps(selection, indent=2, sort_keys=True) + "\n")
    print(json.dumps(selection, indent=2, sort_keys=True), flush=True)

    bucket = Bucket()
    download(main_rows, args.root / "input" / "main", bucket)
    download(trade_rows, args.root / "input" / "trades", bucket)
    if args.download_only:
        return
    replay = BaselineReplay()
    report = replay.consume(
        merge_events(
            bounded_events(args.root / "input" / "main", main_rows, args.start, args.end),
            bounded_events(args.root / "input" / "trades", trade_rows, args.start, args.end),
        )
    )
    report["selection"] = selection
    report["classification"] = selection["classification"]
    write_report(output / "baseline-report.json", report)
    print(json.dumps(report, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
