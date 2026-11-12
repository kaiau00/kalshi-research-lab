"""Apply the frozen T1 rules to results/sports_raw.jsonl."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
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
RAW = ROOT / "results" / "sports_raw.jsonl"
OUT = ROOT / "results" / "sports_summary.json"
TRADES = ROOT / "results" / "sports_trades.jsonl"
COLLEGE = {"cbb", "ncaab", "ncaam"}


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def group_rows(rows: list[dict]) -> dict:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["band"]].append(row)
        if row["lead"]:
            grouped["LEAD_0.85-0.97"].append(row)
    return {name: _summ(items) for name, items in sorted(grouped.items())}


def _summ(items: list[dict]) -> dict:
    return summarize(
        [Decimal(item["pnl"]) for item in items],
        [Decimal(item["price"]) for item in items],
        [Decimal(item["payoff"]) for item in items],
    )


def classify(row: dict) -> dict | None:
    long_price = dec(row.get("longPrice"))
    short_price = dec(row.get("shortPrice"))
    settlement = dec(row.get("settlement"))
    hist_ts = row.get("hist_ts")
    if long_price is None or short_price is None or settlement is None or hist_ts is None:
        return None
    if settlement < 0 or settlement > 1:
        return None
    if not (Decimal(0) < long_price < 1 and Decimal(0) < short_price < 1):
        return None
    start = parse_time(row["gameStartTime"])
    stamp = datetime.fromtimestamp(int(hist_ts), tz=timezone.utc)
    age = (start - stamp).total_seconds()
    fresh = 10 * 60 <= age <= 45 * 60
    spread = spread_proxy(long_price, short_price)
    tight = spread <= Decimal("0.03")
    if long_price == short_price:
        return None
    if long_price > short_price:
        side, price, payoff = "long", long_price, settlement
    else:
        side, price, payoff = "short", short_price, Decimal(1) - settlement
    band = favorite_band(price)
    if band is None:
        return None
    pnl = per_contract_pnl(payoff, price, THETA_RETAIL, PRIMARY_CLIP)
    pnl_new = per_contract_pnl(payoff, price, THETA_NEW_USER, PRIMARY_CLIP)
    pnl_one = per_contract_pnl(payoff, price, THETA_RETAIL, 1)
    question = (row.get("question") or "").lower()
    league = (row.get("league") or "").lower()
    return {
        "slug": row["slug"],
        "league": league,
        "sportsMarketType": row.get("sportsMarketType"),
        "question": row.get("question"),
        "side": side,
        "price": float(price),
        "payoff": float(payoff),
        "spread": float(spread),
        "band": band,
        "lead": lead_band(price),
        "fresh": fresh,
        "tight": tight,
        "primary": fresh and tight,
        "pnl": float(pnl),
        "pnl_new_user": float(pnl_new),
        "pnl_one_lot": float(pnl_one),
        "itf": league.startswith("itf") or "itf" in question,
        "college_basketball": league in COLLEGE,
        "cheap": Decimal("0.03") <= min(long_price, short_price) < Decimal("0.15"),
    }


def cheap_control(rows: list[dict]) -> list[dict]:
    """Buy the cheap display on primary rows, as the longshot control."""
    out = []
    for row in rows:
        if not (row["primary"] and row["cheap"]):
            continue
        # The stored row is the favorite trade. Rebuild the cheap side from payoff identity.
        favorite_payoff = Decimal(str(row["payoff"]))
        cheap_payoff = Decimal(1) - favorite_payoff
        # Cheap price is not stored. Skip unless we can recover it from the spread and favorite price.
        # spread = favorite_ask + cheap_ask - 1, so cheap_ask = spread - favorite + 1.
        cheap_price = Decimal(str(row["spread"])) - Decimal(str(row["price"])) + Decimal(1)
        if not (Decimal("0.03") <= cheap_price < Decimal("0.15")):
            continue
        pnl = per_contract_pnl(cheap_payoff, cheap_price, THETA_RETAIL, PRIMARY_CLIP)
        out.append({"pnl": float(pnl), "price": float(cheap_price), "payoff": float(cheap_payoff)})
    return out


def main() -> None:
    raw_rows = [json.loads(line) for line in RAW.read_text().splitlines() if line.strip()]
    trades = []
    exclusions = {"no_history_or_settlement": 0, "outside_band_or_tied": 0}
    for row in raw_rows:
        classified = classify(row)
        if classified is None:
            if row.get("hist_ts") is None or row.get("settlement") is None:
                exclusions["no_history_or_settlement"] += 1
            else:
                exclusions["outside_band_or_tied"] += 1
            continue
        trades.append(classified)
    primary = [row for row in trades if row["primary"]]
    fresh_only = [row for row in trades if row["fresh"]]
    by_league: dict[str, list[dict]] = defaultdict(list)
    for row in primary:
        if row["lead"]:
            by_league[row["league"]].append(row)
    league_summary = {
        league: summarize(
            [Decimal(str(item["pnl"])) for item in items],
            [Decimal(str(item["price"])) for item in items],
            [Decimal(str(item["payoff"])) for item in items],
        )
        for league, items in sorted(by_league.items())
        if len(items) >= 15 or league in COLLEGE or league == "itf"
    }
    itf = [row for row in primary if row["lead"] and row["itf"]]
    college = [row for row in primary if row["lead"] and row["college_basketball"]]
    summary = {
        "rules": "PREREG.md T1",
        "markets_read": len(raw_rows),
        "classified": len(trades),
        "exclusions": exclusions,
        "primary_n": len(primary),
        "primary_by_band": group_rows(primary),
        "fresh_ignoring_spread": group_rows(fresh_only),
        "all_quotes_ignoring_fresh_and_spread": group_rows(trades),
        "lead_by_league_primary_n_at_least_15_or_prespecified": league_summary,
        "itf_lead_primary": _summ(itf),
        "college_basketball_lead_primary": _summ(college),
        "cheap_side_primary": summarize(
            [Decimal(str(item["pnl"])) for item in cheap_control(trades)],
            [Decimal(str(item["price"])) for item in cheap_control(trades)],
            [Decimal(str(item["payoff"])) for item in cheap_control(trades)],
        ),
        "new_user_fee_on_primary_lead": summarize(
            [Decimal(str(item["pnl_new_user"])) for item in primary if item["lead"]],
            [Decimal(str(item["price"])) for item in primary if item["lead"]],
            [Decimal(str(item["payoff"])) for item in primary if item["lead"]],
        ),
        "one_lot_fee_on_primary_lead": summarize(
            [Decimal(str(item["pnl_one_lot"])) for item in primary if item["lead"]],
            [Decimal(str(item["price"])) for item in primary if item["lead"]],
            [Decimal(str(item["payoff"])) for item in primary if item["lead"]],
        ),
    }
    OUT.write_text(json.dumps(summary, indent=2) + "\n")
    with TRADES.open("w") as handle:
        for row in trades:
            handle.write(json.dumps(row) + "\n")
    lead = summary["primary_by_band"].get("LEAD_0.85-0.97", {})
    print(json.dumps({"primary_n": len(primary), "lead": lead, "itf": summary["itf_lead_primary"], "college": summary["college_basketball_lead_primary"]}, indent=2))


if __name__ == "__main__":
    main()
