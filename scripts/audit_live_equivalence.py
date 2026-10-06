"""Compare settled demo fills with exact production arrival snapshots."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from research_lab.engine import entry_fee
from research_lab.settings import Experiment

CAP = Decimal("3.00")


def _quantity(price, cfg):
    count = int(CAP / price)
    while count and price * count + entry_fee(price, count, cfg) > CAP:
        count -= 1
    return count


def _summary(rows):
    net = sum((row["pnl"] for row in rows), Decimal(0))
    positive = sorted((row["pnl"] for row in rows if row["pnl"] > 0), reverse=True)
    top_three = sum(positive[:3], Decimal(0))
    equity = peak = Decimal("125.00")
    drawdown = Decimal(0)
    daily = defaultdict(Decimal)
    for row in rows:
        equity += row["pnl"]
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
        daily[row["day"]] += row["pnl"]
    return {
        "trades": len(rows),
        "net_pnl": str(net),
        "pnl_without_top_three_winners": str(net - top_three),
        "top_three_winner_pnl": str(top_three),
        "top_three_share_of_positive_pnl": (
            float(top_three / sum(positive, Decimal(0))) if positive else None
        ),
        "maximum_drawdown": str(drawdown),
        "wins": sum(row["pnl"] > 0 for row in rows),
        "losses": sum(row["pnl"] < 0 for row in rows),
        "observed_utc_dates": sorted(daily),
        "positive_day_share": (
            sum(value > 0 for value in daily.values()) / len(daily) if daily else None
        ),
    }


def _percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int((len(values) - 1) * fraction))]


def audit(path):
    cfg = Experiment()
    sql = """
        SELECT i.client_id,i.ticker,i.created_ns,i.decision,i.exchange_order,
               p.snapshot,s.response,s.pnl
        FROM intents i
        JOIN production_audits p ON p.client_id=i.client_id AND p.stage='arrival'
        JOIN settlements s ON s.ticker=i.ticker
        ORDER BY i.created_ns
    """
    with sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True) as db:
        raw_rows = list(db.execute(sql))

    filled = []
    for client_id, ticker, created_ns, decision, exchange, snapshot, settlement, demo_pnl in raw_rows:
        if not exchange:
            continue
        exchange = json.loads(exchange)
        if Decimal(exchange.get("fill_count_fp", "0")) <= 0:
            continue
        filled.append({
            "client_id": client_id,
            "ticker": ticker,
            "created_ns": created_ns,
            "decision": json.loads(decision),
            "snapshot": json.loads(snapshot),
            "settlement": json.loads(settlement),
            "demo_pnl": Decimal(demo_pnl),
        })

    reasons = Counter()
    transferable = []
    used_tickers = set()
    for row in filled:
        snapshot = row["snapshot"]
        if row["ticker"] in used_tickers:
            reasons["duplicate_ticker_after_hypothetical_fill"] += 1
            continue
        if not snapshot.get("available"):
            reasons[snapshot.get("reason", "production_snapshot_unavailable")] += 1
            continue
        if not snapshot.get("qualifies"):
            if not snapshot.get("book_fresh"):
                reasons["stale_production_book"] += 1
            elif not snapshot.get("fees_supported"):
                reasons["production_fee_not_supported"] += 1
            elif not snapshot.get("market_active"):
                reasons["production_market_not_active"] += 1
            else:
                reasons["production_edge_below_threshold"] += 1
            continue
        plan = snapshot.get("risk_sizing", {}).get("variants", {}).get("fixed_3")
        if not plan or int(plan["contracts"]) < 1:
            reasons["zero_contracts_under_cap"] += 1
            continue
        if not plan["depth_sufficient"]:
            reasons["insufficient_displayed_depth"] += 1
            continue
        count = int(plan["contracts"])
        won = row["settlement"]["market_result"] == row["decision"]["side"]
        day = datetime.fromtimestamp(row["created_ns"] / 1e9, timezone.utc).date().isoformat()
        transferable.append({
            "ticker": row["ticker"],
            "day": day,
            "won": won,
            "pnl": Decimal(count if won else 0) - Decimal(plan["modeled_cost"]),
            "demo_pnl": row["demo_pnl"],
            "price": Decimal(snapshot["selected_ask"]),
            "depth": Decimal(snapshot["selected_depth"]),
            "capture_delay_ms": float(snapshot.get("capture_delay_ms", 0)),
        })
        used_tickers.add(row["ticker"])

    stressed = {}
    for cents in (1, 2):
        cases, unfillable = [], 0
        for row in transferable:
            price = row["price"] + Decimal(cents) / 100
            count = _quantity(price, cfg) if price < 1 else 0
            if count < 1 or row["depth"] < count:
                unfillable += 1
                continue
            cost = price * count + entry_fee(price, count, cfg)
            cases.append({
                "day": row["day"],
                "pnl": Decimal(count if row["won"] else 0) - cost,
            })
        stressed[f"{cents}_cent_worse"] = _summary(cases) | {
            "unfillable_after_stress": unfillable,
        }

    demo_all = [{
        "day": datetime.fromtimestamp(row["created_ns"] / 1e9, timezone.utc).date().isoformat(),
        "pnl": row["demo_pnl"],
    } for row in filled]
    demo_transferable = [{"day": row["day"], "pnl": row["demo_pnl"]}
                         for row in transferable]
    capture_delays = [float(row["snapshot"].get("capture_delay_ms", 0)) for row in filled]
    timely = [row for row in transferable if abs(row["capture_delay_ms"]) <= 250]

    return {
        "scope": "Settled demo fills with exact production arrival snapshots; same side; fixed $3 cap.",
        "demo_fills_with_settled_exact_capture": len(filled),
        "production_transfer_rate": len(transferable) / len(filled) if filled else None,
        "non_transfer_reasons": dict(reasons),
        "arrival_capture_delay_ms": {
            "median": _percentile(capture_delays, 0.5),
            "p95": _percentile(capture_delays, 0.95),
            "maximum": max(capture_delays, default=None),
            "mean": sum(capture_delays) / len(capture_delays) if capture_delays else None,
            "over_250ms": sum(abs(value) > 250 for value in capture_delays),
            "over_500ms": sum(abs(value) > 500 for value in capture_delays),
        },
        "demo_all_exact_capture": _summary(demo_all),
        "demo_on_transferable_subset": _summary(demo_transferable),
        "production_equivalent_fixed_3": _summary(transferable),
        "production_equivalent_within_250ms_of_arrival": _summary(timely),
        "stress": stressed,
        "limitations": [
            "Displayed production depth is not a guaranteed fill.",
            "The audit tests whether demo-selected trades transfer to production; it does not invent production-only signals.",
            "One position per ticker is assumed after the first hypothetical production fill.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path,
                        default=Path("/data/demo-adaptive-volatility-001/orders.sqlite3"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.db)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temp = args.output.with_suffix(args.output.suffix + ".tmp")
        with temp.open("w") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(args.output)
    print(rendered, end="")


if __name__ == "__main__":
    main()
