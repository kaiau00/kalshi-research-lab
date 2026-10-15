from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from historical_archive.downloader import download, parse_utc


def main():
    parser = argparse.ArgumentParser(description="Download read-only official KXBTC15M history")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--start", required=True, help="Inclusive UTC ISO date or timestamp")
    parser.add_argument("--end", required=True, help="Exclusive UTC ISO date or timestamp")
    parser.add_argument("--max-markets", type=int, default=20_000)
    parser.add_argument("--no-benchmark", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(
        download(
            args.db,
            start_ts=parse_utc(args.start),
            end_ts=parse_utc(args.end),
            max_markets=args.max_markets,
            include_benchmark=not args.no_benchmark,
            resume=args.resume,
            progress=lambda stage, done, total: print(f"{stage}: {done}/{total}", flush=True),
        )
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

