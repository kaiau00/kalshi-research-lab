"""Apply the frozen T3 favorite rules to results/crypto_raw.jsonl."""

from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from common import (
    PRIMARY_CLIP,
    THETA_NEW_USER,
    THETA_RETAIL,
    dec,
    favorite_band,
    lead_band,
    per_contract_pnl,
    spread_proxy,
    summarize,
)

ROOT = Path(__file__).resolve().parents[1]


def _summ(items: list[dict]) -> dict:
    return summarize(
        [Decimal(str(item["pnl"])) for item in items],
        [Decimal(str(item["price"])) for item in items],
        [Decimal(str(item["payoff"])) for item in items],
    )


def classify(row: dict) -> dict | None:
    long_price = dec(row.get("longPrice"))
    short_price = dec(row.get("shortPrice"))
    beat = dec(row.get("priceToBeat"))
    settle = dec(row.get("settlementPrice"))
    if None in {long_price, short_price, beat, settle} or row.get("hist_ts") is None:
        return None
    assert long_price is not None and short_price is not None and beat is not None and settle is not None
    if not (Decimal(0) < long_price < 1 and Decimal(0) < short_price < 1):
        return None
    if long_price == short_price:
        return None
    up_won = settle >= beat
    spread = spread_proxy(long_price, short_price)
    tight = spread <= Decimal("0.04")
    if long_price > short_price:
        side, price, payoff = "up", long_price, Decimal(1 if up_won else 0)
    else:
        side, price, payoff = "down", short_price, Decimal(0 if up_won else 1)
    band = favorite_band(price)
    if band is None:
        return None
    return {
        "slug": row["slug"],
        "symbol": row.get("symbol"),
        "horizon": row.get("horizon"),
        "side": side,
        "price": float(price),
        "payoff": float(payoff),
        "spread": float(spread),
        "band": band,
        "lead": lead_band(price),
        "tight": tight,
        "pnl": float(per_contract_pnl(payoff, price, THETA_RETAIL, PRIMARY_CLIP)),
        "pnl_new_user": float(per_contract_pnl(payoff, price, THETA_NEW_USER, PRIMARY_CLIP)),
        "pnl_one_lot": float(per_contract_pnl(payoff, price, THETA_RETAIL, 1)),
        "up_won": up_won,
        "move": float((settle - beat) / beat) if beat != 0 else None,
    }


def main() -> None:
    raw = [json.loads(line) for line in (ROOT / "results" / "crypto_raw.jsonl").read_text().splitlines() if line.strip()]
    trades = [row for row in (classify(item) for item in raw) if row is not None]
    primary = [row for row in trades if row["tight"]]
    by_band: dict[str, list[dict]] = defaultdict(list)
    for row in primary:
        by_band[row["band"]].append(row)
        if row["lead"]:
            by_band["LEAD_0.85-0.97"].append(row)
        key = f"{row['symbol']}-{row['horizon']}"
        if row["lead"]:
            by_band[f"LEAD:{key}"].append(row)
    cheap = []
    for row in primary:
        cheap_price = Decimal(str(row["spread"])) - Decimal(str(row["price"])) + Decimal(1)
        if Decimal("0.02") <= cheap_price < Decimal("0.15"):
            payoff = Decimal(1) - Decimal(str(row["payoff"]))
            cheap.append(
                {
                    "pnl": float(per_contract_pnl(payoff, cheap_price, THETA_RETAIL, PRIMARY_CLIP)),
                    "price": float(cheap_price),
                    "payoff": float(payoff),
                }
            )
    summary = {
        "rules": "PREREG.md T3",
        "markets_read": len(raw),
        "classified": len(trades),
        "missing_quote_or_settlement": sum(1 for row in raw if classify(row) is None),
        "primary_n": len(primary),
        "by_band": {name: _summ(items) for name, items in sorted(by_band.items())},
        "cheap_side": summarize(
            [Decimal(str(item["pnl"])) for item in cheap],
            [Decimal(str(item["price"])) for item in cheap],
            [Decimal(str(item["payoff"])) for item in cheap],
        ),
        "new_user_lead": _summ(
            [
                {**row, "pnl": row["pnl_new_user"]}
                for row in primary
                if row["lead"]
            ]
        ),
        "one_lot_lead": _summ([{**row, "pnl": row["pnl_one_lot"]} for row in primary if row["lead"]]),
    }
    (ROOT / "results" / "crypto_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    with (ROOT / "results" / "crypto_trades.jsonl").open("w") as handle:
        for row in trades:
            handle.write(json.dumps(row) + "\n")
    print(json.dumps({"read": len(raw), "primary": len(primary), "lead": summary["by_band"].get("LEAD_0.85-0.97")}, indent=2))


if __name__ == "__main__":
    main()
