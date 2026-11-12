"""Apply the frozen T4 pilot rules to results/live_samples.jsonl.

Settlements are fetched here, after the windows have ended. The entry rule
does not look at those settlements.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from common import PM, PRIMARY_CLIP, THETA_RETAIL, RateLimiter, dec, get_json, per_contract_pnl

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = datetime(2026, 11, 12, 16, 15, tzinfo=timezone.utc)


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main() -> None:
    path = ROOT / "results" / "live_samples.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
    by_slug: dict[str, list[dict]] = {}
    for row in rows:
        if row.get("error") or not row.get("windowEnd"):
            continue
        by_slug.setdefault(row["slug"], []).append(row)
    limiter = RateLimiter(4)
    trades = []
    windows = []
    for slug, samples in sorted(by_slug.items()):
        end = parse_time(samples[0]["windowEnd"])
        if end < CUTOFF:
            continue
        samples.sort(key=lambda item: item["t"])
        market = get_json(f"{PM}/v1/market/slug/{slug}", limiter)
        body = market.get("market") or market
        terms = body.get("assetPriceTerms") or {}
        beat = dec((terms.get("priceToBeat") or {}).get("value") if isinstance(terms.get("priceToBeat"), dict) else None)
        settle = dec((terms.get("settlementPrice") or {}).get("value") if isinstance(terms.get("settlementPrice"), dict) else None)
        windows.append(
            {
                "slug": slug,
                "windowEnd": samples[0]["windowEnd"],
                "samples": len(samples),
                "priceToBeat": None if beat is None else str(beat),
                "settlementPrice": None if settle is None else str(settle),
                "resolved": settle is not None,
            }
        )
        if beat is None or settle is None or beat == 0:
            continue
        up_won = settle >= beat
        for label, low, high in (("20-40s", 20, 40), ("60-90s", 60, 90), ("5-15s", 5, 15)):
            chosen = [sample for sample in samples if low <= float(sample["seconds_left"]) <= high]
            if not chosen:
                trades.append({"slug": slug, "bucket": label, "status": "no_sample"})
                continue
            sample = max(chosen, key=lambda item: item["t"])
            index = dec(sample.get("index"))
            bid = dec(sample.get("bestBid"))
            long_price = dec(sample.get("longPrice")) or dec(sample.get("bestAsk"))
            short_price = dec(sample.get("shortPrice"))
            if short_price is None and bid is not None:
                short_price = Decimal(1) - bid
            if index is None or long_price is None or short_price is None:
                trades.append({"slug": slug, "bucket": label, "status": "missing_quote"})
                continue
            spread = long_price + short_price - Decimal(1)
            distance_bps = (index - beat) / beat * Decimal(10000)
            favorite_up = distance_bps >= 2
            favorite_down = distance_bps <= -2
            if favorite_up:
                side, side_ask, payoff = "up", long_price, Decimal(1 if up_won else 0)
            elif favorite_down:
                side, side_ask, payoff = "down", short_price, Decimal(0 if up_won else 1)
            else:
                trades.append(
                    {
                        "slug": slug,
                        "bucket": label,
                        "status": "inside_2bps",
                        "distance_bps": float(distance_bps),
                        "yes_ask": float(long_price),
                        "spread": float(spread),
                    }
                )
                continue
            gate = Decimal("0.80") <= side_ask <= Decimal("0.98") and spread <= Decimal("0.04")
            pnl = per_contract_pnl(payoff, side_ask, THETA_RETAIL, PRIMARY_CLIP)
            trades.append(
                {
                    "slug": slug,
                    "bucket": label,
                    "status": "trade" if gate else "failed_price_or_spread_gate",
                    "side": side,
                    "ask": float(side_ask),
                    "spread": float(spread),
                    "distance_bps": float(distance_bps),
                    "payoff": float(payoff),
                    "pnl": float(pnl) if gate else None,
                    "up_won": up_won,
                }
            )
    taken = [row for row in trades if row.get("status") == "trade"]
    summary = {
        "rules": "PREREG.md T4",
        "samples": len(rows),
        "windows_after_cutoff": windows,
        "trades": trades,
        "taken_n": len(taken),
        "taken_mean_pnl": None
        if not taken
        else float(sum(Decimal(str(row["pnl"])) for row in taken) / Decimal(len(taken))),
        "taken_sum_pnl_25lot": None if not taken else float(sum(Decimal(str(row["pnl"])) for row in taken) * PRIMARY_CLIP),
    }
    (ROOT / "results" / "live_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"samples": len(rows), "windows": len(windows), "taken": len(taken), "mean": summary["taken_mean_pnl"]}, indent=2))


if __name__ == "__main__":
    main()
