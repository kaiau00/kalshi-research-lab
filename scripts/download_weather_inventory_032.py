#!/usr/bin/env python3
"""Create a bounded, immutable raw Kalshi weather-market inventory for Study 032."""

import argparse
import json
from pathlib import Path

from weather_research.inventory import run

parser = argparse.ArgumentParser()
parser.add_argument("--db", type=Path, required=True)
parser.add_argument("--series", default="KXHIGHNY")
parser.add_argument("--max-pages", type=int, default=4)
parser.add_argument("--resume", action="store_true")
args = parser.parse_args()
print(json.dumps(run(args.db, series=args.series, max_pages=args.max_pages, resume=args.resume), indent=2, sort_keys=True))
