"""Compare published up/down reference prices to the public 1-second series.

Rules: PREREG.md T3 identity check. Descriptive. Not a PnL test.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode

from common import PM, RateLimiter, dec, get_json

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = datetime(2026, 11, 12, 16, 10, tzinfo=timezone.utc)
SYMBOLS = ("btc", "eth", "sol", "xrp")
HORIZONS = ("5m", "15m", "1h")
ASSET = {"btc": "crypto:btc", "eth": "crypto:eth", "sol": "crypto:sol", "xrp": "crypto:xrp"}


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def collect(limiter: RateLimiter) -> list[dict]:
    # Recent closed crypto, newest hours first, until each cell has 8.
    wanted = {f"{symbol}-{horizon}": [] for symbol in SYMBOLS for horizon in HORIZONS}
    hour_end = CUTOFF.replace(minute=0, second=0, microsecond=0)
    from datetime import timedelta

    scanned = 0
    while scanned < 18 and any(len(rows) < 8 for rows in wanted.values()):
        hour_start = hour_end - timedelta(hours=1)
        offset = 0
        while True:
            query = urlencode(
                {
                    "closed": "true",
                    "categories": "crypto",
                    "endDateMin": hour_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "endDateMax": hour_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "limit": 100,
                    "offset": offset,
                }
            )
            markets = get_json(f"{PM}/v1/markets?{query}", limiter).get("markets") or []
            for market in markets:
                terms = market.get("assetPriceTerms") or {}
                symbol = (terms.get("asset") or {}).get("symbol")
                horizon = terms.get("horizon")
                key = f"{symbol}-{horizon}"
                if key not in wanted or len(wanted[key]) >= 8:
                    continue
                if terms.get("marketType") != "ASSET_PRICE_MARKET_TYPE_UP_DOWN":
                    continue
                end = terms.get("windowEnd")
                if not end or parse_time(end) >= CUTOFF:
                    continue
                wanted[key].append(
                    {
                        "slug": market["slug"],
                        "symbol": symbol,
                        "horizon": horizon,
                        "windowStart": terms.get("windowStart"),
                        "windowEnd": end,
                        "priceToBeat": (terms.get("priceToBeat") or {}).get("value"),
                        "settlementPrice": (terms.get("settlementPrice") or {}).get("value"),
                    }
                )
            if len(markets) < 100:
                break
            offset += 100
        print(f"identity hour {hour_start.isoformat()} " + " ".join(f"{k}:{len(v)}" for k, v in wanted.items()), flush=True)
        hour_end = hour_start
        scanned += 1
    rows = [row for group in wanted.values() for row in group]
    return rows


def closes(limiter: RateLimiter, asset: str, start: int, end: int) -> dict[int, Decimal]:
    query = urlencode(
        {
            "assets": asset,
            "from": start,
            "to": end,
            "bucket": "ASSET_PRICE_BUCKET_1S",
        }
    )
    payload = get_json(f"{PM}/v1/asset-prices/history?{query}", limiter)
    series = payload.get("series") or []
    if not series:
        return {}
    out = {}
    for candle in series[0].get("candles") or []:
        price = dec(candle.get("close"))
        if price is not None:
            out[int(candle["timestamp"])] = price
    return out


def exact(published: Decimal | None, other: Decimal | None) -> bool:
    if published is None or other is None:
        return False
    return published == other


def evaluate(row: dict, limiter: RateLimiter) -> dict:
    symbol = row["symbol"]
    start = int(parse_time(row["windowStart"]).timestamp())
    end = int(parse_time(row["windowEnd"]).timestamp())
    series = closes(limiter, ASSET[symbol], start - 70, end + 2)
    # The open window and the close window are an hour apart on 1h markets, so fetch both.
    if start - 70 not in series and (end - start) > 120:
        series.update(closes(limiter, ASSET[symbol], start - 70, start + 2))
    settle_last = series.get(end - 1)
    open_last = series.get(start - 1)
    settle_mean_vals = [series[t] for t in range(end - 60, end) if t in series]
    open_mean_vals = [series[t] for t in range(start - 60, start) if t in series]
    settle_mean = sum(settle_mean_vals, Decimal(0)) / Decimal(len(settle_mean_vals)) if len(settle_mean_vals) == 60 else None
    open_mean = sum(open_mean_vals, Decimal(0)) / Decimal(len(open_mean_vals)) if len(open_mean_vals) == 60 else None
    published_settle = dec(row.get("settlementPrice"))
    published_open = dec(row.get("priceToBeat"))
    return {
        **row,
        "settle_close_t_minus_1": None if settle_last is None else str(settle_last),
        "open_close_t_minus_1": None if open_last is None else str(open_last),
        "settle_mean_60": None if settle_mean is None else str(settle_mean),
        "open_mean_60": None if open_mean is None else str(open_mean),
        "settle_exact_last": exact(published_settle, settle_last),
        "settle_exact_mean": exact(published_settle, settle_mean.quantize(Decimal("0.01"))) if settle_mean is not None and published_settle is not None else False,
        "open_exact_last": exact(published_open, open_last),
        "n_settle_seconds": len(settle_mean_vals),
        "n_open_seconds": len(open_mean_vals),
        "settle_abs_err_last": None if published_settle is None or settle_last is None else str(abs(published_settle - settle_last)),
        "settle_abs_err_mean": None if published_settle is None or settle_mean is None else str(abs(published_settle - settle_mean)),
    }


def main() -> None:
    limiter = RateLimiter(3)
    rows = collect(limiter)
    print(f"identity markets {len(rows)}", flush=True)
    evaluated = []
    for index, row in enumerate(rows, start=1):
        try:
            evaluated.append(evaluate(row, limiter))
        except Exception as error:  # noqa: BLE001
            evaluated.append({**row, "error": f"{type(error).__name__}: {error}"})
        if index % 10 == 0:
            print(f"identity {index}/{len(rows)}", flush=True)
    usable = [row for row in evaluated if row.get("settle_abs_err_last") is not None]
    summary = {
        "rules": "PREREG.md T3 identity",
        "markets": len(evaluated),
        "usable_settlement_comparisons": len(usable),
        "settlement_exact_match_close_at_T_minus_1": sum(1 for row in usable if row["settle_exact_last"]),
        "open_exact_match_close_at_T_minus_1": sum(1 for row in usable if row["open_exact_last"]),
        "settlement_closer_to_last_than_to_60s_mean": sum(
            1
            for row in usable
            if row.get("settle_abs_err_mean") is not None
            and Decimal(row["settle_abs_err_last"]) < Decimal(row["settle_abs_err_mean"])
        ),
        "median_abs_err_last": _median(Decimal(row["settle_abs_err_last"]) for row in usable),
        "median_abs_err_mean": _median(
            Decimal(row["settle_abs_err_mean"]) for row in usable if row.get("settle_abs_err_mean")
        ),
        "rows": evaluated,
    }
    (ROOT / "results" / "brti_identity.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in summary if k != "rows"}, indent=2))


def _median(values) -> str | None:
    items = sorted(values)
    if not items:
        return None
    mid = len(items) // 2
    if len(items) % 2:
        return str(items[mid])
    return str((items[mid - 1] + items[mid]) / 2)


if __name__ == "__main__":
    main()
