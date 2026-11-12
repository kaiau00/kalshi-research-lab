"""List settled sports winners and pull the pre-game display plus the settlement.

Writes results/sports_markets.jsonl and results/sports_raw.jsonl.
Rules: PREREG.md section T1. No outcome table is printed here.
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode

from common import PM, RateLimiter, get_json, league_token

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
KEEP_SUFFIXES = ("full_game_winner", "match_winner", "fight_winner")
EXCLUDED = {"aec-nfl-lv-sf-2026-11-08"}
# Amendment A in PREREG.md: October was dropped before any price was read.
START = datetime(2026, 11, 1, tzinfo=timezone.utc)
END_SCAN = datetime(2026, 11, 13, tzinfo=timezone.utc)
GAME_LO = "2026-11-01T00:00:00Z"
GAME_HI = "2026-11-12T12:00:00Z"


def keep(market: dict) -> bool:
    kind = market.get("sportsMarketType") or ""
    if kind == "moneyline" or kind.endswith(KEEP_SUFFIXES):
        slug = market.get("slug") or ""
        start = market.get("gameStartTime") or ""
        return bool(slug) and slug not in EXCLUDED and GAME_LO <= start < GAME_HI
    return False


def list_markets(limiter: RateLimiter) -> list[dict]:
    found: dict[str, dict] = {}
    day = START
    while day < END_SCAN:
        nxt = day + timedelta(days=1)
        offset = 0
        while True:
            query = urlencode(
                {
                    "closed": "true",
                    "categories": "sports",
                    "endDateMin": day.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "endDateMax": nxt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "limit": 100,
                    "offset": offset,
                }
            )
            payload = get_json(f"{PM}/v1/markets?{query}", limiter)
            markets = payload.get("markets") or []
            for market in markets:
                if keep(market):
                    slug = market["slug"]
                    long_side = next((side for side in market.get("marketSides") or [] if side.get("long")), {})
                    short_side = next((side for side in market.get("marketSides") or [] if not side.get("long")), {})
                    found[slug] = {
                        "slug": slug,
                        "question": market.get("question"),
                        "sportsMarketType": market.get("sportsMarketType"),
                        "league": league_token(slug),
                        "gameStartTime": market.get("gameStartTime"),
                        "endDate": market.get("endDate"),
                        "feeCoefficient": market.get("feeCoefficient"),
                        "listed_long_price": long_side.get("price"),
                        "listed_short_price": short_side.get("price"),
                    }
            print(f"list {day.date()} offset {offset} page {len(markets)} kept {len(found)}", flush=True)
            if len(markets) < 100:
                break
            offset += 100
            if offset > 20000:
                print(f"TRUNCATED {day.date()} at offset {offset}", flush=True)
                break
        day = nxt
    return list(found.values())


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def fetch_one(market: dict, limiter: RateLimiter) -> dict:
    row = dict(market)
    start = parse_time(market["gameStartTime"])
    window_lo = int((start - timedelta(hours=3)).timestamp())
    window_hi = int((start - timedelta(minutes=10)).timestamp())
    url = (
        f"{PM}/v1/price-history?symbol={market['slug']}"
        f"&timestamp.startTimestamp={window_lo}&timestamp.endTimestamp={window_hi}&fidelity=1"
    )
    try:
        history = get_json(url, limiter).get("history") or []
    except Exception as error:  # noqa: BLE001 — record and continue
        history = []
        row["history_error"] = f"{type(error).__name__}: {error}"
    eligible = [point for point in history if window_lo <= int(point.get("timestamp") or 0) <= window_hi]
    if eligible:
        point = max(eligible, key=lambda item: int(item["timestamp"]))
        row["hist_ts"] = int(point["timestamp"])
        row["longPrice"] = point.get("longPrice")
        row["shortPrice"] = point.get("shortPrice")
        row["hist_points"] = len(eligible)
    else:
        row["hist_ts"] = None
        row["longPrice"] = None
        row["shortPrice"] = None
        row["hist_points"] = 0
    def resolved_side(value: object) -> str | None:
        try:
            number = Decimal(str(value))
        except Exception:
            return None
        if number in {Decimal(0), Decimal(1), Decimal("0.5")}:
            return format(number, "f")
        return None

    listed_long = resolved_side(row.get("listed_long_price"))
    listed_short = resolved_side(row.get("listed_short_price"))
    if listed_long is not None and listed_short is not None:
        row["settlement"] = listed_long
        row["settlement_source"] = "listed_side_price"
    else:
        try:
            settlement = get_json(f"{PM}/v1/markets/{market['slug']}/settlement", limiter)
            row["settlement"] = settlement.get("settlement")
            row["settlement_source"] = "settlement_endpoint"
        except Exception as error:  # noqa: BLE001
            row["settlement"] = None
            row["settlement_error"] = f"{type(error).__name__}: {error}"
    return row


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    limiter = RateLimiter(12)
    markets_path = RESULTS / "sports_markets.jsonl"
    raw_path = RESULTS / "sports_raw.jsonl"
    if markets_path.exists() and markets_path.stat().st_size > 0:
        markets = [json.loads(line) for line in markets_path.read_text().splitlines() if line.strip()]
        print(f"reuse {len(markets)} listed markets", flush=True)
    else:
        markets = list_markets(limiter)
        with markets_path.open("w") as handle:
            for market in markets:
                handle.write(json.dumps(market) + "\n")
        print(f"listed {len(markets)}", flush=True)
    done: set[str] = set()
    if raw_path.exists():
        for line in raw_path.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["slug"])
    pending = [market for market in markets if market["slug"] not in done]
    print(f"fetch {len(pending)} remaining, {len(done)} already stored", flush=True)
    with raw_path.open("a") as handle, ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fetch_one, market, limiter) for market in pending]
        for index, future in enumerate(as_completed(futures), start=1):
            row = future.result()
            handle.write(json.dumps(row) + "\n")
            handle.flush()
            if index % 50 == 0:
                print(f"fetched {index}/{len(pending)}", flush=True)
    print("sports collect done", flush=True)


if __name__ == "__main__":
    sys.exit(main())
