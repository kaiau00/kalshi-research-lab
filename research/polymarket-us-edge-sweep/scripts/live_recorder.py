"""Record BTC and ETH up/down books and the public index through upcoming windows.

Rules for which rows count: PREREG.md T4. This process only records.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from common import PM, RateLimiter, get_json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "live_samples.jsonl"
PAIRS = (
    ("btc", "cpc-btc-updown", "crypto:btc"),
    ("eth", "cpceth-eth-updown", "crypto:eth"),
)


def stamp(moment: datetime) -> str:
    moment = moment.astimezone(timezone.utc).replace(second=0, microsecond=0)
    return moment.strftime("%Y-%m-%d-") + moment.strftime("%H%M") + "z"


def window_start(now: datetime, minutes: int) -> datetime:
    now = now.astimezone(timezone.utc).replace(second=0, microsecond=0)
    return now.replace(minute=(now.minute // minutes) * minutes)


def quote(slug: str, limiter: RateLimiter) -> dict:
    payload = get_json(f"{PM}/v1/market/slug/{slug}", limiter)
    market = payload.get("market") or payload
    terms = market.get("assetPriceTerms") or {}

    def px(field: str) -> str | None:
        value = market.get(field)
        if isinstance(value, dict):
            return value.get("value")
        return None

    long_price = None
    short_price = None
    for side in market.get("marketSides") or []:
        if side.get("long"):
            long_price = side.get("price")
        else:
            short_price = side.get("price")
    return {
        "slug": slug,
        "windowStart": terms.get("windowStart"),
        "windowEnd": terms.get("windowEnd"),
        "priceToBeat": (terms.get("priceToBeat") or {}).get("value") if isinstance(terms.get("priceToBeat"), dict) else None,
        "bestBid": px("bestBidQuote"),
        "bestAsk": px("bestAskQuote"),
        "longPrice": long_price,
        "shortPrice": short_price,
        "state": market.get("status") or market.get("ep3Status"),
    }


def index_now(limiter: RateLimiter) -> dict[str, str | None]:
    now = int(time.time())
    query = urlencode(
        [
            ("assets", "crypto:btc"),
            ("assets", "crypto:eth"),
            ("from", now - 5),
            ("to", now),
            ("bucket", "ASSET_PRICE_BUCKET_1S"),
        ]
    )
    payload = get_json(f"{PM}/v1/asset-prices/history?{query}", limiter)
    out: dict[str, str | None] = {}
    for series in payload.get("series") or []:
        symbol = (series.get("asset") or {}).get("symbol")
        candles = series.get("candles") or []
        out[symbol] = candles[-1]["close"] if candles else None
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=2100)
    args = parser.parse_args()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    limiter = RateLimiter(4)
    deadline = time.time() + args.seconds
    print(f"recording until {datetime.now(timezone.utc) + timedelta(seconds=args.seconds)}", flush=True)
    with OUT.open("a") as handle:
        while time.time() < deadline:
            loop_started = time.time()
            now = datetime.now(timezone.utc)
            try:
                spot = index_now(limiter)
            except Exception as error:  # noqa: BLE001
                spot = {}
                print("index error", error, flush=True)
            for symbol, prefix, _asset in PAIRS:
                for minutes in (5, 15):
                    start = window_start(now, minutes)
                    end = start + timedelta(minutes=minutes)
                    seconds_left = (end - now).total_seconds()
                    if not (0 < seconds_left <= 180):
                        continue
                    slug = f"{prefix}-{minutes}m-{stamp(start)}"
                    try:
                        book = quote(slug, limiter)
                    except Exception as error:  # noqa: BLE001
                        book = {"slug": slug, "error": f"{type(error).__name__}: {error}"}
                    row = {
                        "t": now.isoformat(),
                        "symbol": symbol,
                        "horizon": f"{minutes}m",
                        "seconds_left": round(seconds_left, 2),
                        "index": spot.get(symbol),
                        **book,
                    }
                    handle.write(json.dumps(row) + "\n")
                    handle.flush()
            sleep_for = 5 - (time.time() - loop_started)
            if sleep_for > 0:
                time.sleep(sleep_for)
    print("recorder done", flush=True)


if __name__ == "__main__":
    main()
