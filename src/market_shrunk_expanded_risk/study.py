from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

from historical_frequency_optimization.study import build_tape
from historical_market_confirmation.kelly import run_variant
from historical_market_confirmation.kelly_registration import SIGNAL
from historical_market_confirmation.study import _normalize, select_decisions
from research_lab.settings import Experiment
from research_lab.storage import canonical

from .registration import EXPECTED_FIXED_LEDGER, RISK_GRID, registration, registration_hash


def _ranking(results: dict, metric):
    return sorted(results, key=lambda name: (metric(results[name]), name), reverse=True)


def run_study(database: Path, audit_path: Path):
    source = build_tape(database, audit_path)
    cfg = Experiment()
    decisions, rejections = select_decisions(source["tape"], SIGNAL, cfg)
    decisions = _normalize(decisions)
    fixed = run_variant(decisions, "fixed_1", source["observed_days"], cfg)
    if fixed["trade_ledger_sha256"] != EXPECTED_FIXED_LEDGER:
        raise ValueError("Study 027 fixed-$1 replay does not reproduce Study 023")

    results = {}
    for name, settings in RISK_GRID.items():
        multiplier = Decimal(settings["multiplier"])
        base_variant = "kelly_1_4_cap_3" if multiplier == Decimal("0.25") else "kelly_1_2_cap_3"
        summary = run_variant(
            decisions,
            base_variant,
            source["observed_days"],
            cfg,
            kelly_cap=Decimal(settings["cap_dollars"]),
            kelly_multiplier=multiplier,
            result_name=name,
        )
        summary["kelly_multiplier"] = settings["multiplier"]
        summary["all_in_cap_dollars"] = settings["cap_dollars"]
        results[name] = summary

    for fraction in ("quarter", "half"):
        baseline = results[f"{fraction}_kelly_cap_3"]
        for cap in (3, 4, 5, 6):
            summary = results[f"{fraction}_kelly_cap_{cap}"]
            summary["incremental_vs_cap_3"] = {
                "net_pnl": str(Decimal(summary["net_pnl"]) - Decimal(baseline["net_pnl"])),
                "two_cent_stressed_pnl": str(
                    Decimal(summary["stressed_pnl"]["2"])
                    - Decimal(baseline["stressed_pnl"]["2"])
                ),
                "maximum_drawdown": str(
                    Decimal(summary["maximum_drawdown"])
                    - Decimal(baseline["maximum_drawdown"])
                ),
            }

    highest_base = _ranking(results, lambda row: Decimal(row["net_pnl"]))
    highest_stress = _ranking(results, lambda row: Decimal(row["stressed_pnl"]["2"]))
    best_ratio = _ranking(
        results,
        lambda row: Decimal(row["two_cent_stress_to_drawdown"] or "-Infinity"),
    )
    report = {
        "study": "027",
        "state": "complete_risk_diagnostic",
        "registration": registration(),
        "registration_sha256": registration_hash(),
        "source": {
            "eligible_research_markets": source["eligible_markets"],
            "observed_utc_dates": len(source["observed_days"]),
            "holdout_markets": source["holdout_markets"],
            "holdout_evaluated": False,
        },
        "signal": SIGNAL,
        "decision_rejections": dict(sorted(rejections.items())),
        "fixed_1_replay": fixed,
        "risk_results": results,
        "rankings": {
            "highest_base_pnl": highest_base,
            "highest_two_cent_stressed_pnl": highest_stress,
            "best_two_cent_stress_to_drawdown": best_ratio,
        },
        "production_change_authorized": False,
        "production_orders_authorized": False,
        "holdout": {"locked": True, "evaluated": False},
    }
    report["report_sha256"] = hashlib.sha256(canonical(report)).hexdigest()
    return report


def public_summary(report: dict):
    return {
        key: value
        for key, value in report.items()
        if key not in {"registration", "decision_rejections"}
    }
