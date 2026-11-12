"""Settled BTC/ETH up-down markets and the quote about one minute before the end.

Rules: PREREG.md section T3. Prints progress only, not the PnL table.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from common import PM, RateLimiter, get_json

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
LO = datetime(2026, 11, 11, tzinfo=timezone.utc)
HI = datetime(2026, 11, 12, 11, tzinfo=timezone.utc)
SYMBOLS = {"btc", "eth"}
HORIZONS = {"5m", "15m"}


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def list_markets(limiter: RateLimiter) -> list[dict]:
    found: dict[str, dict] = {}
    # Closed crypto markets are dense. Page by endDate hour.
    hour = LO
    from datetime import timedelta

    while hour < HI:
        nxt = hour + timedelta(hours=1)
        offset = 0
        while True:
            query = urlencode(
                {
                    "closed": "true",
                    "categories": "crypto",
                    "endDateMin": hour.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "endDateMax": nxt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "limit": 100,
                    "offset": offset,
                }
            )
            markets = get_json(f"{PM}/v1/markets?{query}", limiter).get("markets") or []
            for market in markets:
                terms = market.get("assetPriceTerms") or {}
                symbol = (terms.get("asset") or {}).get("symbol")
                if (
                    terms.get("marketType") == "ASSET_PRICE_MARKET_TYPE_UP_DOWN"
                    and symbol in SYMBOLS
                    and terms.get("horizon") in HORIZONS
                ):
                    end = terms.get("windowEnd")
                    if not end:
                        continue
                    end_dt = parse_time(end)
                    if not (LO <= end_dt < HI):
                        continue
                    found[market["slug"]] = {
                        "slug": market["slug"],
                        "symbol": symbol,
                        "horizon": terms.get("horizon"),
                        "windowStart": terms.get("windowStart"),
                        "windowEnd": end,
                        "priceToBeat": (terms.get("priceToBeat") or {}).get("value"),
                        "settlementPrice": (terms.get("settlementPrice") or {}).get("value"),
                        "feeCoefficient": market.get("feeCoefficient"),
                    }
            print(f"crypto {hour.isoformat()} offset {offset} page {len(markets)} kept {len(found)}", flush=True)
            if len(markets) < 100:
                break
            offset += 100
            if offset > 5000:
                print(f"TRUNCATED {hour.isoformat()}", flush=True)
                break
        hour = nxt
    return list(found.values())


def fetch_one(market: dict, limiter: RateLimiter) -> dict:
    row = dict(market)
    end = int(parse_time(market["windowEnd"]).timestamp())
    url = (
        f"{PM}/v1/price-history?symbol={market['slug']}"
        f"&timestamp.startTimestamp={end - 180}&timestamp.endTimestamp={end + 30}&fidelity=1"
    )
    try:
        history = get_json(url, limiter).get("history") or []
    except Exception as error:  # noqa: BLE001
        history = []
        row["history_error"] = f"{type(error).__name__}: {error}"
    eligible = [point for point in history if end - 90 <= int(point.get("timestamp") or 0) <= end - 60]
    if eligible:
        point = max(eligible, key=lambda item: int(item["timestamp"]))
        row["hist_ts"] = int(point["timestamp"])
        row["longPrice"] = point.get("longPrice")
        row["shortPrice"] = point.get("shortPrice")
    else:
        row["hist_ts"] = None
        row["longPrice"] = None
        row["shortPrice"] = None
    if row.get("settlementPrice") is None or row.get("priceToBeat") is None:
        try:
            fresh = get_json(f"{PM}/v1/market/slug/{market['slug']}", limiter)
            market_body = fresh.get("market") or fresh
            terms = market_body.get("assetPriceTerms") or {}
            row["priceToBeat"] = row.get("priceToBeat") or (terms.get("priceToBeat") or {}).get("value")
            row["settlementPrice"] = row.get("settlementPrice") or (terms.get("settlementPrice") or {}).get("value")
        except Exception as error:  # noqa: BLE001
            row["refetch_error"] = f"{type(error).__name__}: {error}"
    return row


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    limiter = RateLimiter(3)
    listed_path = RESULTS / "crypto_markets.jsonl"
    raw_path = RESULTS / "crypto_raw.jsonl"
    if listed_path.exists() and listed_path.stat().st_size > 0:
        markets = [json.loads(line) for line in listed_path.read_text().splitlines() if line.strip()]
        print(f"reuse {len(markets)} crypto markets", flush=True)
    else:
        markets = list_markets(limiter)
        with listed_path.open("w") as handle:
            for market in markets:
                handle.write(json.dumps(market) + "\n")
    done = set()
    if raw_path.exists():
        for line in raw_path.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["slug"])
    pending = [market for market in markets if market["slug"] not in done]
    print(f"fetch {len(pending)} crypto histories", flush=True)
    with raw_path.open("a") as handle, ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fetch_one, market, limiter) for market in pending]
        for index, future in enumerate(as_completed(futures), start=1):
            handle.write(json.dumps(future.result()) + "\n")
            handle.flush()
            if index % 40 == 0:
                print(f"crypto fetched {index}/{len(pending)}", flush=True)
    print("crypto collect done", flush=True)


if __name__ == "__main__":
    main()
