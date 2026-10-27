#!/usr/bin/env python3
"""Build one exact local replay cache from already verified Study 029 archives."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hft_research.baseline_replay import merge_events
from hft_research.normalized_cache import write_cache
from research_lab.segments import checksum

# `scripts` is imported for the shared, tested selection helpers when this
# file is executed directly rather than as a module.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.hft_forward_replay_029 import (
    bounded_events,
    parse_time,
    select_segments,
    selection_metadata,
)


def verified_stream(root: Path, rows: list[dict], start_ns: int, end_ns: int):
    for row in rows:
        path = root / Path(row["archive_key"]).name
        if not path.exists() or checksum(path) != row["archive_sha"]:
            raise ValueError(f"Missing or unverified local archive: {path}")
    return bounded_events(root, rows, start_ns, end_ns)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-catalog", type=Path, required=True)
    parser.add_argument("--trade-catalog", type=Path, required=True)
    parser.add_argument("--start", type=parse_time, required=True)
    parser.add_argument("--end", type=parse_time, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()

    main_rows = select_segments(args.main_catalog, args.start, args.end)
    trade_rows = select_segments(args.trade_catalog, args.start, args.end)
    if not main_rows or not trade_rows:
        raise SystemExit("Selected interval has no complete main or public-trade segments")
    source = {
        "study": "029",
        "requested_start_ns": args.start,
        "requested_end_ns": args.end,
        "main": selection_metadata("main", main_rows),
        "trade": selection_metadata("trade", trade_rows),
    }
    events = merge_events(
        verified_stream(args.root / "main", main_rows, args.start, args.end),
        verified_stream(args.root / "trades", trade_rows, args.start, args.end),
    )
    print(json.dumps(write_cache(args.cache, events, source), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
