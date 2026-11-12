"""Small public inventory: event counts by tag, and spreads on open league games.

This does not re-scan all 25k markets. Yesterday's full inventory is cited in the report.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode

from common import PM, RateLimiter, dec, get_json

ROOT = Path(__file__).resolve().parents[1]
TAGS = ("politics", "sports", "crypto", "culture", "climate", "weather", "economics", "finance", "mentions", "world")
LEAGUES = ("nfl", "nba", "ncaab", "cbb", "wnba", "nhl", "mlb", "atp", "wta", "itf", "ufc", "epl", "mls")


def event_count(tag: str, limiter: RateLimiter, end_max: str | None = None) -> int | None:
    def page(offset: int) -> int:
        params = {"limit": 1, "offset": offset, "active": "true", "closed": "false", "tagSlug": tag}
        if end_max:
            params["endDateMax"] = end_max
        query = urlencode(params)
        try:
            events = get_json(f"{PM}/v1/events?{query}", limiter, timeout=60).get("events") or []
        except Exception as error:  # noqa: BLE001
            print("count error", tag, error, flush=True)
            return -1
        return len(events)

    if page(0) == 0:
        return 0
    if page(0) < 0:
        return None
    low, high = 0, 1
    while page(high) > 0 and high < 20000:
        low = high
        high *= 2
    if high >= 20000 and page(high) > 0:
        return None
    while high - low > 1:
        mid = (low + high) // 2
        if page(mid) > 0:
            low = mid
        else:
            high = mid
    return low + 1


def league_spreads(league: str, limiter: RateLimiter) -> dict:
    try:
        payload = get_json(f"{PM}/v2/leagues/{league}/events?limit=30&type=sport", limiter)
    except Exception as error:  # noqa: BLE001
        return {"league": league, "error": f"{type(error).__name__}: {error}"}
    spreads = []
    wide = 0
    two_sided = 0
    for event in payload.get("events") or []:
        for market in event.get("markets") or []:
            kind = market.get("sportsMarketType") or ""
            if not (kind.endswith("winner") or kind == "moneyline"):
                continue
            bid = dec((market.get("bestBidQuote") or {}).get("value") if isinstance(market.get("bestBidQuote"), dict) else None)
            ask = dec((market.get("bestAskQuote") or {}).get("value") if isinstance(market.get("bestAskQuote"), dict) else None)
            if bid is None or ask is None:
                continue
            two_sided += 1
            spread = ask - bid
            spreads.append(spread)
            if spread >= Decimal("0.03"):
                wide += 1
    spreads.sort()
    median = None if not spreads else spreads[len(spreads) // 2]
    return {
        "league": league,
        "events": len(payload.get("events") or []),
        "two_sided_winner_quotes": two_sided,
        "median_spread": None if median is None else float(median),
        "spread_at_least_3c": wide,
    }


def macro_sample(limiter: RateLimiter) -> list[dict]:
    rows = []
    for tag in ("economics", "finance", "climate", "culture", "mentions"):
        query = urlencode({"limit": 8, "active": "true", "closed": "false", "tagSlug": tag})
        try:
            events = get_json(f"{PM}/v1/events?{query}", limiter).get("events") or []
        except Exception as error:  # noqa: BLE001
            rows.append({"tag": tag, "error": f"{type(error).__name__}: {error}"})
            continue
        for event in events:
            rows.append(
                {
                    "tag": tag,
                    "slug": event.get("slug"),
                    "title": event.get("title"),
                    "endDate": event.get("endDate"),
                    "closed": event.get("closed"),
                    "markets": len(event.get("markets") or []),
                }
            )
    return rows


def main() -> None:
    limiter = RateLimiter(4)
    counts = {}
    for tag in TAGS:
        open_n = event_count(tag, limiter)
        past_n = event_count(tag, limiter, end_max="2026-11-12T16:05:00Z")
        counts[tag] = {"open_events": open_n, "open_and_past_end": past_n}
        print(tag, counts[tag], flush=True)
    leagues = [league_spreads(league, limiter) for league in LEAGUES]
    summary = {
        "note": "Event counts are from offset binary search on the public events list. "
        "A null count means the probe did not finish. League spreads are the open winner "
        "markets returned for that league, up to 30 events.",
        "event_counts": counts,
        "league_spreads": leagues,
        "tag_samples": macro_sample(limiter),
    }
    (ROOT / "results" / "inventory.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("inventory done", flush=True)


if __name__ == "__main__":
    main()
