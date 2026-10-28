#!/usr/bin/env python3
"""Collect a bounded, source-segmented public Kalshi candle archive for Study 032."""

import argparse
import asyncio
import json
from pathlib import Path

from weather_research.candles import download, select_markets

parser = argparse.ArgumentParser()
parser.add_argument("--inventory", type=Path, required=True)
parser.add_argument("--db", type=Path, required=True)
parser.add_argument("--source", default="The Weather Company")
parser.add_argument("--max-event-dates", type=int, default=10)
parser.add_argument("--max-contracts", type=int, default=100)
parser.add_argument("--resume", action="store_true")
args = parser.parse_args()
markets = select_markets(
    args.inventory,
    source=args.source,
    max_event_dates=args.max_event_dates,
    max_contracts=args.max_contracts,
)
result = asyncio.run(download(args.db, markets=markets, source=args.source, resume=args.resume))
print(json.dumps(result, indent=2, sort_keys=True))
