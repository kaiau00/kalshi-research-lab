"""Turn politics books into executable 97–99¢ candidates. Does not assign winners."""

from __future__ import annotations

import json
import random
from decimal import Decimal
from pathlib import Path

from common import dec

ROOT = Path(__file__).resolve().parents[1]
LO = Decimal("0.97")
HI = Decimal("0.995")


def main() -> None:
    payload = json.loads((ROOT / "results" / "politics_events.json").read_text())
    events = payload["events"]
    candidates = []
    display_only = []
    market_count = 0
    for event in events:
        for market in event["markets"]:
            market_count += 1
            book = market.get("book") or {}
            yes_ask = dec(book.get("yes_ask"))
            yes_bid = dec(book.get("yes_bid"))
            if yes_ask is not None and LO <= yes_ask < HI:
                candidates.append(
                    {
                        "event": event["slug"],
                        "title": event["title"],
                        "endDate": event["endDate"],
                        "resolutionSource": event.get("resolutionSource"),
                        "slug": market["slug"],
                        "question": market.get("question"),
                        "side": "yes",
                        "side_label": next((s["description"] for s in market["sides"] if s.get("long")), None),
                        "ask": float(yes_ask),
                        "ask_qty": book.get("yes_ask_qty"),
                        "winner_market": market.get("winner_market"),
                    }
                )
            if yes_bid is not None:
                no_ask = Decimal(1) - yes_bid
                if LO <= no_ask < HI:
                    candidates.append(
                        {
                            "event": event["slug"],
                            "title": event["title"],
                            "endDate": event["endDate"],
                            "resolutionSource": event.get("resolutionSource"),
                            "slug": market["slug"],
                            "question": market.get("question"),
                            "side": "no",
                            "side_label": next((s["description"] for s in market["sides"] if not s.get("long")), None),
                            "ask": float(no_ask),
                            "ask_qty": book.get("yes_bid_qty"),
                            "winner_market": market.get("winner_market"),
                        }
                    )
            for side in market["sides"]:
                price = dec(side.get("price"))
                if price is not None and LO <= price < HI:
                    display_only.append(
                        {
                            "event": event["slug"],
                            "title": event["title"],
                            "endDate": event["endDate"],
                            "slug": market["slug"],
                            "question": market.get("question"),
                            "label": side.get("description"),
                            "long": side.get("long"),
                            "display": float(price),
                            "winner_market": market.get("winner_market"),
                            "book_yes_ask": None if yes_ask is None else float(yes_ask),
                            "book_yes_bid": None if yes_bid is None else float(yes_bid),
                        }
                    )
    candidates.sort(key=lambda item: (-item["ask"], item["slug"], item["side"]))
    must = [item for item in candidates if item["winner_market"]]
    rest = [item for item in candidates if not item["winner_market"]]
    sample = list(must)
    if len(candidates) <= 40:
        sample = list(candidates)
    else:
        extra = rest[:20]
        pool = rest[20:]
        rng = random.Random(20261112)
        draw = rng.sample(pool, k=min(10, len(pool)))
        seen = {(item["slug"], item["side"]) for item in sample}
        for item in extra + draw:
            key = (item["slug"], item["side"])
            if key not in seen:
                sample.append(item)
                seen.add(key)
    summary = {
        "rules": "PREREG.md T2",
        "events": len(events),
        "markets": market_count,
        "executable_candidates": len(candidates),
        "display_only_97_99": len(display_only),
        "verification_sample_n": len(sample),
        "candidates": candidates,
        "verification_sample": sample,
        "display_only": display_only,
    }
    (ROOT / "results" / "politics_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        json.dumps(
            {
                "events": len(events),
                "markets": market_count,
                "executable": len(candidates),
                "display_only": len(display_only),
                "sample": len(sample),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
