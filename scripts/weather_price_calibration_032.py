#!/usr/bin/env python3
"""Run Study 032's fixed-time exploratory NWS price-calibration screen."""

import argparse
import json
from glob import glob
from pathlib import Path

from research_lab.storage import Store
from weather_research.alignment import contract_event_date
from weather_research.calibration import calibration_report, quotes_at_fixed_horizons
from weather_research.candles import epoch_seconds
from weather_research.inventory import settlement_source
from weather_research.ncei import validate_nws_reference

SOURCE = "National Weather Service — Climatological Report (Daily)"

parser = argparse.ArgumentParser()
parser.add_argument("--inventory", type=Path, required=True)
parser.add_argument("--candles-glob", required=True)
parser.add_argument("--ncei", type=Path, required=True, help="Immutable NCEI reference archive")
args = parser.parse_args()

markets = {}
raw_markets = []
inventory = Store(args.inventory, readonly=True)
try:
    for event in inventory.events():
        if event.kind != "weather_market_page":
            continue
        for market in event.payload["response"].get("markets", []):
            if market.get("status") == "finalized" and settlement_source(market.get("rules_primary", "")) == SOURCE:
                raw_markets.append(market)
                markets[market["ticker"]] = {
                    "event_date": contract_event_date(market),
                    "close_second": epoch_seconds(market["close_time"]),
                    "result": market.get("result"),
                }
finally:
    inventory.close()

ncei_rows = []
ncei = Store(args.ncei, readonly=True)
try:
    for event in ncei.events():
        if event.kind == "ncei_response":
            ncei_rows.extend(event.payload.get("response", []))
finally:
    ncei.close()

reference_validation = validate_nws_reference(raw_markets, ncei_rows)
if not reference_validation["compared_dates"] or reference_validation["matching_dates"] != reference_validation["compared_dates"]:
    raise SystemExit("NCEI reference did not exactly match every compared NWS event date; refusing calibration")
validated_dates = {str(row["DATE"]) for row in ncei_rows if row.get("DATE")}
markets = {ticker: market for ticker, market in markets.items() if market["event_date"] in validated_dates}

candles = {}
for filename in sorted(glob(args.candles_glob)):
    archive = Store(filename, readonly=True)
    try:
        for event in archive.events():
            if event.kind == "weather_candle":
                candles[event.payload["ticker"]] = event.payload["response"].get("candlesticks", [])
    finally:
        archive.close()

report = calibration_report(quotes_at_fixed_horizons(markets, candles))
report["reference_validation"] = reference_validation
report["archive_coverage"] = {
    "validated_nws_markets": len(markets),
    "candle_contracts": len(candles),
    "ncei_event_dates": len(validated_dates),
}
print(json.dumps(report, indent=2, sort_keys=True))
