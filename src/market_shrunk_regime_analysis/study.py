from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from historical_frequency_optimization.study import build_tape
from historical_market_confirmation.kelly import quantity_for_budget, run_variant
from historical_market_confirmation.kelly_registration import SIGNAL
from historical_market_confirmation.study import _normalize, select_decisions
from research_lab.engine import entry_fee
from research_lab.settings import Experiment
from research_lab.storage import canonical

from .registration import (
    EXPECTED_FIXED_LEDGER,
    FEATURES,
    MINIMUM_PARTITION_BUCKET_TRADES,
    registration,
    registration_hash,
)

STARTING_CASH = Decimal("100.00")
FIXED_BUDGET = Decimal("1.00")


def _stress_pnl(trade: dict, cents: int, cfg: Experiment) -> Decimal:
    price = min(Decimal("0.999999"), trade["price"] + Decimal(cents) / 100)
    return trade["payout"] - price * trade["quantity"] - entry_fee(
        price, trade["quantity"], cfg
    )


def build_trades(decisions: list[dict], cfg: Experiment) -> list[dict]:
    cash = STARTING_CASH
    trades = []
    for decision in decisions:
        quantity = quantity_for_budget(decision["price"], FIXED_BUDGET, cash, cfg)
        if quantity < 1:
            continue
        fee = entry_fee(decision["price"], quantity, cfg)
        cost = decision["price"] * quantity + fee
        won = decision["side"] == decision["result"]
        payout = Decimal(quantity if won else 0)
        pnl = payout - cost
        cash += pnl
        trades.append(
            {
                **decision,
                "quantity": quantity,
                "fee": fee,
                "cost": cost,
                "payout": payout,
                "pnl": pnl,
                "won": won,
                "stress_1": _stress_pnl(
                    {**decision, "quantity": quantity, "payout": payout}, 1, cfg
                ),
                "stress_2": _stress_pnl(
                    {**decision, "quantity": quantity, "payout": payout}, 2, cfg
                ),
            }
        )
    return trades


def _range_label(value: float, boundaries: list[tuple[float, str]]) -> str:
    for upper, label in boundaries:
        if value < upper:
            return label
    return boundaries[-1][1]


def feature_value(trade: dict, feature: str) -> str:
    if feature == "side":
        return trade["side"]
    if feature == "entry_price":
        return _range_label(
            float(trade["price"]),
            [(0.55, "45-54"), (0.65, "55-64"), (0.70, "65-69"), (0.75, "70-74"), (math.inf, "75-79")],
        )
    if feature == "seconds_left":
        return _range_label(
            float(trade["seconds_left"]),
            [(61, "5-60"), (121, "61-120"), (181, "121-180"), (241, "181-240"), (math.inf, "241-300")],
        )
    if feature == "absolute_raw_market_gap":
        gap = abs(trade["raw_yes_probability"] - trade["market_yes_probability"])
        return _range_label(
            gap,
            [(0.015, "0-1.49"), (0.03, "1.5-2.99"), (0.05, "3-4.99"), (math.inf, "5-7.5")],
        )
    if feature == "modeled_net_edge":
        return _range_label(
            float(trade["edge"]),
            [(0.02, "0.5-1.99"), (0.04, "2-3.99"), (0.08, "4-7.99"), (math.inf, "8+")],
        )
    if feature == "fast_slow_variance_ratio":
        return _range_label(
            float(trade["fast_slow_variance_ratio"]),
            [(0.5, "0-0.49"), (1.0, "0.5-0.99"), (2.0, "1-1.99"), (math.inf, "2+")],
        )
    if feature == "selected_market_probability":
        probability = trade["market_yes_probability"]
        if trade["side"] == "no":
            probability = 1 - probability
        return _range_label(
            float(probability),
            [(0.35, "20-34"), (0.50, "35-49"), (0.65, "50-64"), (math.inf, "65-80")],
        )
    if feature == "utc_hour":
        hour = datetime.fromtimestamp(trade["created_ns"] / 1e9, timezone.utc).hour
        return ["00-05", "06-11", "12-17", "18-23"][hour // 6]
    if feature == "chronological_block":
        return str(trade["block"] + 1)
    raise ValueError(f"unknown diagnostic feature: {feature}")


def _wilson_interval(wins: int, count: int, z: float = 1.6448536269514722):
    if count == 0:
        return None
    p = wins / count
    denominator = 1 + z * z / count
    center = (p + z * z / (2 * count)) / denominator
    margin = z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / denominator
    return [max(0.0, center - margin), min(1.0, center + margin)]


def summarize(trades: list[dict]) -> dict:
    count = len(trades)
    wins = sum(row["won"] for row in trades)
    pnl = sum((row["pnl"] for row in trades), Decimal(0))
    positive = sorted((row["pnl"] for row in trades if row["pnl"] > 0), reverse=True)
    positive_total = sum(positive, Decimal(0))
    peak = STARTING_CASH
    cash = STARTING_CASH
    drawdown = Decimal(0)
    for row in sorted(trades, key=lambda value: (value["settled_ns"], value["ticker"])):
        cash += row["pnl"]
        peak = max(peak, cash)
        drawdown = max(drawdown, peak - cash)
    return {
        "trades": count,
        "wins": wins,
        "win_rate": wins / count if count else None,
        "win_rate_wilson_90pct": _wilson_interval(wins, count),
        "mean_entry_price": (
            str(sum((row["price"] for row in trades), Decimal(0)) / count) if count else None
        ),
        "fees": str(sum((row["fee"] for row in trades), Decimal(0))),
        "net_pnl": str(pnl),
        "pnl_without_top_three_winners": str(pnl - sum(positive[:3], Decimal(0))),
        "top_three_share_of_positive_pnl": (
            float(sum(positive[:3], Decimal(0)) / positive_total) if positive_total else None
        ),
        "one_cent_stressed_pnl": str(sum((row["stress_1"] for row in trades), Decimal(0))),
        "two_cent_stressed_pnl": str(sum((row["stress_2"] for row in trades), Decimal(0))),
        "maximum_drawdown": str(drawdown),
    }


def _feature_report(trades: list[dict], feature: str):
    buckets = defaultdict(list)
    for trade in trades:
        buckets[feature_value(trade, feature)].append(trade)
    report = []
    for bucket in FEATURES[feature]:
        members = buckets.get(bucket, [])
        development = [row for row in members if row["partition"] == "development"]
        validation = [row for row in members if row["partition"] == "validation"]
        development_summary = summarize(development)
        validation_summary = summarize(validation)
        enough = min(len(development), len(validation)) >= MINIMUM_PARTITION_BUCKET_TRADES
        development_stress = Decimal(development_summary["two_cent_stressed_pnl"])
        validation_stress = Decimal(validation_summary["two_cent_stressed_pnl"])
        report.append(
            {
                "bucket": bucket,
                "aggregate": summarize(members),
                "development": development_summary,
                "validation": validation_summary,
                "minimum_partition_count_met": enough,
                "repeatable_weakness": enough and development_stress < 0 and validation_stress < 0,
                "repeatable_strength": enough and development_stress > 0 and validation_stress > 0,
                "partition_sign_instability": enough and development_stress * validation_stress < 0,
            }
        )
    return report


def run_study(database: Path, audit_path: Path):
    source = build_tape(database, audit_path)
    cfg = Experiment()
    decisions, rejections = select_decisions(source["tape"], SIGNAL, cfg)
    decisions = _normalize(decisions)
    replay = run_variant(decisions, "fixed_1", source["observed_days"], cfg)
    if replay["trade_ledger_sha256"] != EXPECTED_FIXED_LEDGER:
        raise ValueError("Study 025 fixed-$1 replay does not reproduce Study 023")
    trades = build_trades(decisions, cfg)
    features = {name: _feature_report(trades, name) for name in FEATURES}
    repeatable_weaknesses = [
        {"feature": feature, "bucket": row["bucket"], "aggregate": row["aggregate"]}
        for feature, rows in features.items()
        for row in rows
        if row["repeatable_weakness"]
    ]
    repeatable_strengths = [
        {"feature": feature, "bucket": row["bucket"], "aggregate": row["aggregate"]}
        for feature, rows in features.items()
        for row in rows
        if row["repeatable_strength"]
    ]
    unstable = [
        {"feature": feature, "bucket": row["bucket"], "aggregate": row["aggregate"]}
        for feature, rows in features.items()
        for row in rows
        if row["partition_sign_instability"]
    ]
    report = {
        "study": "025",
        "state": "complete_diagnostic",
        "registration": registration(),
        "registration_sha256": registration_hash(),
        "source": {
            "eligible_research_markets": source["eligible_markets"],
            "observed_utc_dates": len(source["observed_days"]),
            "development_utc_dates": len(source["partition_days"]["development"]),
            "validation_utc_dates": len(source["partition_days"]["validation"]),
            "holdout_markets": source["holdout_markets"],
            "holdout_evaluated": False,
        },
        "signal": SIGNAL,
        "decision_rejections": dict(sorted(rejections.items())),
        "fixed_1_replay": replay,
        "overall": summarize(trades),
        "features": features,
        "repeatable_weaknesses": repeatable_weaknesses,
        "repeatable_strengths": repeatable_strengths,
        "partition_sign_instabilities": unstable,
        "conclusion_scope": {
            "exploratory_diagnostic": True,
            "candidate_selected": False,
            "holdout_evaluated": False,
            "production_change_authorized": False,
        },
    }
    report["report_sha256"] = hashlib.sha256(canonical(report)).hexdigest()
    return report


def public_summary(report: dict):
    return {key: value for key, value in report.items() if key not in {"registration", "decision_rejections"}}
