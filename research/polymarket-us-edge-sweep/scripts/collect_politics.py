"""Open politics events whose endDate is already past, and the executable book.

Rules: PREREG.md section T2. Does not decide who won.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlencode

from common import PM, RateLimiter, dec, get_json

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
WINNER_RE = re.compile(r"(governor|senate).{0,60}winner|winner.{0,60}(governor|senate)", re.IGNORECASE)
END_MAX = "2026-11-12T16:05:00Z"


def amount(level: dict | None) -> tuple[str | None, str | None]:
    if not level:
        return None, None
    price = level.get("px") or level.get("price")
    if isinstance(price, dict):
        price = price.get("value")
    qty = level.get("qty")
    return (None if price is None else str(price), None if qty is None else str(qty))


def slim_market(market: dict) -> dict:
    sides = []
    for side in market.get("marketSides") or []:
        sides.append(
            {
                "description": side.get("description"),
                "long": side.get("long"),
                "price": side.get("price"),
            }
        )
    return {
        "slug": market.get("slug"),
        "question": market.get("question"),
        "title": market.get("title"),
        "closed": market.get("closed"),
        "active": market.get("active"),
        "status": market.get("status"),
        "bestAsk": (market.get("bestAskQuote") or {}).get("value") if isinstance(market.get("bestAskQuote"), dict) else None,
        "bestBid": (market.get("bestBidQuote") or {}).get("value") if isinstance(market.get("bestBidQuote"), dict) else None,
        "outcomePrices": market.get("outcomePrices"),
        "sides": sides,
        "winner_market": bool(WINNER_RE.search(market.get("question") or "") or WINNER_RE.search(market.get("title") or "")),
    }


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    limiter = RateLimiter(2)
    events = []
    offset = 0
    while True:
        query = urlencode(
            {
                "limit": 15,
                "offset": offset,
                "active": "true",
                "closed": "false",
                "tagSlug": "politics",
                "endDateMax": END_MAX,
            }
        )
        page = get_json(f"{PM}/v1/events?{query}", limiter, timeout=90).get("events") or []
        print(f"politics events offset {offset} page {len(page)}", flush=True)
        if not page:
            break
        for event in page:
            markets = [slim_market(market) for market in (event.get("markets") or [])]
            events.append(
                {
                    "slug": event.get("slug"),
                    "title": event.get("title"),
                    "endDate": event.get("endDate"),
                    "category": event.get("category"),
                    "resolutionSource": event.get("resolutionSource"),
                    "closed": event.get("closed"),
                    "active": event.get("active"),
                    "markets": markets,
                }
            )
        if len(page) < 15:
            break
        offset += 15
        if offset > 5000:
            print("TRUNCATED politics events", flush=True)
            break
    screened = []
    for event in events:
        for market in event["markets"]:
            if market["slug"] and (
                market["winner_market"]
                or (dec(market["bestAsk"]) is not None and (dec(market["bestAsk"]) <= dec("0.05") or dec(market["bestAsk"]) >= dec("0.95")))
                or any(dec(side["price"]) is not None and (dec(side["price"]) <= dec("0.05") or dec(side["price"]) >= dec("0.95")) for side in market["sides"])
            ):
                screened.append((event["slug"], market["slug"]))
    print(f"events {len(events)} book fetches {len(screened)}", flush=True)
    books: dict[str, dict] = {}
    for index, (_event_slug, slug) in enumerate(screened, start=1):
        try:
            payload = get_json(f"{PM}/v1/markets/{slug}/book", limiter)
        except Exception as error:  # noqa: BLE001
            books[slug] = {"error": f"{type(error).__name__}: {error}"}
            continue
        data = payload.get("marketData") or {}
        bids = data.get("bids") or []
        offers = data.get("offers") or []
        bid_px, bid_qty = amount(bids[0] if bids else None)
        ask_px, ask_qty = amount(offers[0] if offers else None)
        books[slug] = {
            "state": data.get("state"),
            "yes_bid": bid_px,
            "yes_bid_qty": bid_qty,
            "yes_ask": ask_px,
            "yes_ask_qty": ask_qty,
            "bid_levels": len(bids),
            "ask_levels": len(offers),
        }
        if index % 40 == 0:
            print(f"books {index}/{len(screened)}", flush=True)
    for event in events:
        for market in event["markets"]:
            market["book"] = books.get(market["slug"])
    out = RESULTS / "politics_events.json"
    out.write_text(json.dumps({"endDateMax": END_MAX, "events": events}, indent=2) + "\n")
    print(f"wrote {out} events {len(events)}", flush=True)


if __name__ == "__main__":
    main()
