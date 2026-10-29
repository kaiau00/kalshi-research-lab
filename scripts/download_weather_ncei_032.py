#!/usr/bin/env python3
"""Archive one bounded NCEI daily-summary window for Study 032's NWS branch."""

import argparse
import asyncio
import json
from pathlib import Path

from weather_research.ncei import DailySummaryRequest, download

parser = argparse.ArgumentParser()
parser.add_argument("--db", type=Path, required=True)
parser.add_argument("--start-date", required=True)
parser.add_argument("--end-date", required=True)
parser.add_argument("--resume", action="store_true")
args = parser.parse_args()

result = asyncio.run(
    download(
        args.db,
        requests=[DailySummaryRequest(args.start_date, args.end_date)],
        resume=args.resume,
    )
)
print(json.dumps(result, indent=2, sort_keys=True))
