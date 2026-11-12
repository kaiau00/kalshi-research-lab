"""Polymarket US hourly above/below versus Kalshi threshold markets.

One discovery pass, then 20 minutes of quote refreshes on the strikes that
were inside 3 percent of the index. Rules: PREREG.md T5.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode

from common import KALSHI, PM, THETA_KALSHI, THETA_RETAIL, RateLimiter, ceil_cent, dec, get_json

ROOT = Path(__file__).resolve().parents[1]
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
PAIRS = (("btc", "KXBTCD", "cpc-btc-above-hr", "crypto:btc"), ("eth", "KXETHD", "cpceth-eth-above-hr", "crypto:eth"))


def kalshi_ticker_suffix(moment: datetime) -> str:
    est = moment.astimezone(timezone.utc) + timedelta(hours=-5)
    return f"{est.year % 100:02d}{MONTHS[est.month - 1]}{est.day:02d}{est.hour:02d}"


def upcoming_hours(now: datetime) -> list[datetime]:
    now = now.astimezone(timezone.utc)
    hour = now.replace(minute=0, second=0, microsecond=0)
    if now > hour:
        hour += timedelta(hours=1)
    return [hour + timedelta(hours=step) for step in range(3)]


def raw_fee(theta: Decimal, price: Decimal) -> Decimal:
    return theta * price * (Decimal(1) - price)


def load_pm(limiter: RateLimiter) -> list[dict]:
    markets = []
    offset = 0
    while offset < 2500:
        query = urlencode({"active": "true", "closed": "false", "categories": "crypto", "limit": 100, "offset": offset})
        page = get_json(f"{PM}/v1/markets?{query}", limiter).get("markets") or []
        markets.extend(page)
        if len(page) < 100:
            break
        offset += 100
    return markets


def load_kalshi(event: str, limiter: RateLimiter) -> tuple[dict[Decimal, dict], str | None, str | None]:
    payload = get_json(f"{KALSHI}/events/{event}?with_nested_markets=true", limiter)
    body = payload.get("event") or payload
    found: dict[Decimal, dict] = {}
    rules = None
    for market in body.get("markets") or []:
        if market.get("strike_type") != "greater":
            continue
        floor = dec(market.get("floor_strike"))
        if floor is None:
            continue
        strike = (floor + Decimal("0.01")).quantize(Decimal("1"))
        found[strike] = market
        rules = rules or market.get("rules_primary")
    return found, rules, body.get("title")


def spot(asset: str, limiter: RateLimiter) -> Decimal | None:
    now = int(time.time())
    query = urlencode({"assets": asset, "from": now - 5, "to": now, "bucket": "ASSET_PRICE_BUCKET_1S"})
    payload = get_json(f"{PM}/v1/asset-prices/history?{query}", limiter)
    candles = ((payload.get("series") or [{}])[0]).get("candles") or []
    return dec(candles[-1]["close"]) if candles else None


def pm_quote(market: dict) -> tuple[Decimal | None, Decimal | None]:
    bid = market.get("bestBidQuote")
    ask = market.get("bestAskQuote")
    return (
        dec(bid.get("value") if isinstance(bid, dict) else None),
        dec(ask.get("value") if isinstance(ask, dict) else None),
    )


def compare_row(symbol: str, expiry: str, strike: Decimal, index: Decimal, pm_market: dict, kalshi_market: dict) -> dict:
    if abs(index - strike) <= 1:
        return {"symbol": symbol, "expiry": expiry, "strike": str(strike), "status": "within_1_dollar"}
    pm_bid, pm_ask = pm_quote(pm_market)
    k_bid = dec(kalshi_market.get("yes_bid_dollars"))
    k_ask = dec(kalshi_market.get("yes_ask_dollars"))
    if None in {pm_bid, pm_ask, k_bid, k_ask}:
        return {"symbol": symbol, "expiry": expiry, "strike": str(strike), "status": "missing_side"}
    assert pm_bid is not None and pm_ask is not None and k_bid is not None and k_ask is not None
    # Unrounded per-contract fees, the primary figure in PREREG T5.
    buy_pm = k_bid - pm_ask - raw_fee(THETA_RETAIL, pm_ask) - raw_fee(THETA_KALSHI, k_bid)
    buy_k = pm_bid - k_ask - raw_fee(THETA_KALSHI, k_ask) - raw_fee(THETA_RETAIL, pm_bid)
    rounded_buy_pm = k_bid - pm_ask - (ceil_cent(raw_fee(THETA_RETAIL, pm_ask) * 10) / 10) - (
        ceil_cent(raw_fee(THETA_KALSHI, k_bid) * 10) / 10
    )
    return {
        "symbol": symbol,
        "expiry": expiry,
        "strike": str(strike),
        "status": "quoted",
        "distance": str(index - strike),
        "pm_bid": str(pm_bid),
        "pm_ask": str(pm_ask),
        "kalshi_bid": str(k_bid),
        "kalshi_ask": str(k_ask),
        "kalshi_bid_size": kalshi_market.get("yes_bid_size_fp"),
        "kalshi_ask_size": kalshi_market.get("yes_ask_size_fp"),
        "pm_slug": pm_market.get("slug"),
        "kalshi_ticker": kalshi_market.get("ticker"),
        "net_buy_pm_sell_kalshi": str(buy_pm),
        "net_buy_kalshi_sell_pm": str(buy_k),
        "net_buy_pm_sell_kalshi_ceil_10lot": str(rounded_buy_pm),
        "positive": buy_pm > 0 or buy_k > 0,
    }


def discover(limiter: RateLimiter) -> dict:
    now = datetime.now(timezone.utc)
    hours = upcoming_hours(now)
    pm_markets = load_pm(limiter)
    tracked = []
    rules = {}
    for symbol, series, prefix, asset in PAIRS:
        index = spot(asset, limiter)
        if index is None:
            continue
        for moment in hours:
            suffix = kalshi_ticker_suffix(moment)
            event = f"{series}-{suffix}"
            pm_stamp = moment.strftime("%Y-%m-%d-") + moment.strftime("%H%M") + "z"
            needle = f"{prefix}-{pm_stamp}-"
            pm_by_strike = {}
            for market in pm_markets:
                slug = market.get("slug") or ""
                if not slug.startswith(needle):
                    continue
                terms = market.get("assetPriceTerms") or {}
                strike = dec((terms.get("strike") or {}).get("value") if isinstance(terms.get("strike"), dict) else None)
                if strike is not None:
                    pm_by_strike[strike] = market
            try:
                kalshi, rule, title = load_kalshi(event, limiter)
            except Exception as error:  # noqa: BLE001
                rules[event] = {"error": f"{type(error).__name__}: {error}"}
                continue
            rules[event] = {"title": title, "rules_primary": rule}
            for strike, market in pm_by_strike.items():
                other = kalshi.get(strike)
                if other is None:
                    continue
                if abs(index - strike) / index > Decimal("0.03"):
                    continue
                tracked.append(
                    {
                        "symbol": symbol,
                        "asset": asset,
                        "expiry": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "strike": strike,
                        "slug": market["slug"],
                        "event": event,
                        "ticker": other.get("ticker"),
                    }
                )
    return {"tracked": tracked, "rules": rules, "discovered_at": now.isoformat()}


def refresh(tracked: list[dict], limiter: RateLimiter) -> dict:
    now = datetime.now(timezone.utc)
    by_event: dict[str, dict[Decimal, dict]] = {}
    indexes: dict[str, Decimal | None] = {}
    for symbol, _series, _prefix, asset in PAIRS:
        indexes[symbol] = spot(asset, limiter)
    events = {item["event"] for item in tracked}
    for event in events:
        try:
            book, _rule, _title = load_kalshi(event, limiter)
            by_event[event] = book
        except Exception as error:  # noqa: BLE001
            by_event[event] = {}
            print("kalshi refresh error", event, error, flush=True)
    rows = []
    for item in tracked:
        index = indexes.get(item["symbol"])
        if index is None:
            continue
        try:
            payload = get_json(f"{PM}/v1/market/slug/{item['slug']}", limiter)
        except Exception as error:  # noqa: BLE001
            rows.append({"slug": item["slug"], "status": "pm_error", "error": f"{type(error).__name__}: {error}"})
            continue
        market = payload.get("market") or payload
        kalshi_market = by_event.get(item["event"], {}).get(item["strike"])
        if kalshi_market is None:
            rows.append({"slug": item["slug"], "status": "kalshi_missing"})
            continue
        rows.append(compare_row(item["symbol"], item["expiry"], item["strike"], index, market, kalshi_market))
    return {"t": now.isoformat(), "spot": {key: None if value is None else str(value) for key, value in indexes.items()}, "comparisons": rows}


def main() -> None:
    limiter = RateLimiter(4)
    print("discovering ladders", flush=True)
    found = discover(limiter)
    print(f"tracking {len(found['tracked'])} strike pairs", flush=True)
    passes = []
    deadline = time.time() + 20 * 60
    while True:
        passes.append(refresh(found["tracked"], limiter))
        quoted = [row for row in passes[-1]["comparisons"] if row.get("status") == "quoted"]
        positive = [row for row in quoted if row.get("positive")]
        print(f"pass {len(passes)} quoted {len(quoted)} positive {len(positive)}", flush=True)
        if time.time() >= deadline:
            break
        time.sleep(30)
    positive_rows = [row for snap in passes for row in snap["comparisons"] if row.get("positive")]
    # Rules text can be long. Keep one copy, trimmed.
    rules_out = {}
    for event, body in found["rules"].items():
        text = body.get("rules_primary") or ""
        rules_out[event] = {"title": body.get("title"), "error": body.get("error"), "rules_primary_head": text[:500]}
    summary = {
        "rules": "PREREG.md T5 kalshi. Unrounded per-contract fees are the primary net. "
        "A cent-ceiling 10-lot variant is also stored. Tracked strikes are within 3 percent of the index.",
        "tracked": [
            {key: (str(value) if isinstance(value, Decimal) else value) for key, value in item.items()}
            for item in found["tracked"]
        ],
        "rules_text": rules_out,
        "passes": len(passes),
        "quoted_observations": sum(1 for snap in passes for row in snap["comparisons"] if row.get("status") == "quoted"),
        "positive_observations": len(positive_rows),
        "positive": positive_rows,
        "snapshots": passes,
    }
    (ROOT / "results" / "kalshi_cross.json").write_text(json.dumps(summary) + "\n")
    print(json.dumps({"passes": len(passes), "positive": len(positive_rows), "tracked": len(found["tracked"])}, indent=2))


if __name__ == "__main__":
    main()
