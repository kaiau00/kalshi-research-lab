from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

from historical_frequency_optimization.study import build_tape
from historical_robust_optimization.registration import RISK_VARIANTS
from historical_robust_optimization.study import run_sizing
from research_lab.settings import Experiment
from research_lab.storage import canonical

from .study import _normalize, _risk_recommendation, select_decisions
from .validation_registration import CONFIGURATION, registration, registration_hash

EXPECTED_DEVELOPMENT_LEDGER = "7d86eba8d136a45129974695ca1f00a14173ed233e9ec1f6b881539a2ec34db1"


def _trades_per_day(summary: dict):
    return summary["settled_markets"] / summary["observed_days"]


def _price_in_range(summary: dict):
    value = summary["entry_diagnostics"]["mean_entry_price"]
    return value is not None and Decimal("0.45") <= Decimal(value) <= Decimal("0.72")


def validation_gates(summary: dict):
    frequency = _trades_per_day(summary)
    return {
        "average_4_to_7_trades_per_day": 4 <= frequency <= 7,
        "minimum_65pct_win_rate": summary["win_rate"] is not None and summary["win_rate"] >= 0.65,
        "mean_entry_price_45_to_72_cents": _price_in_range(summary),
        "positive_base_pnl": Decimal(summary["realized_net_pnl"]) > 0,
        "positive_pnl_without_top_three": Decimal(summary["pnl_without_top_three_winners"]) > 0,
        "positive_one_cent_stress": Decimal(summary["stressed_pnl"]["1"]) > 0,
        "positive_two_cent_stress": Decimal(summary["stressed_pnl"]["2"]) > 0,
        "positive_on_majority_of_days": summary["positive_day_share"] is not None
        and summary["positive_day_share"] > 0.5,
        "positive_in_three_of_five_base_blocks": summary["positive_blocks"] >= 3,
        "positive_two_cent_stress_in_three_of_five_blocks": summary[
            "positive_two_cent_stressed_blocks"
        ]
        >= 3,
        "maximum_drawdown_at_most_5": Decimal(summary["maximum_drawdown"]) <= 5,
    }


def aggregate_gates(summary: dict):
    frequency = _trades_per_day(summary)
    return {
        "average_4_to_7_trades_per_day": 4 <= frequency <= 7,
        "base_pnl_exceeds_study_020": Decimal(summary["realized_net_pnl"]) > Decimal("24.4806"),
        "pnl_without_top_three_exceeds_study_020": Decimal(
            summary["pnl_without_top_three_winners"]
        )
        > Decimal("21.2847"),
        "two_cent_stress_exceeds_study_020": Decimal(summary["stressed_pnl"]["2"])
        > Decimal("9.2233"),
        "positive_in_four_of_five_base_blocks": summary["positive_blocks"] >= 4,
        "positive_two_cent_stress_in_four_of_five_blocks": summary[
            "positive_two_cent_stressed_blocks"
        ]
        >= 4,
        "maximum_drawdown_at_most_10": Decimal(summary["maximum_drawdown"]) <= 10,
        "positive_one_sided_90pct_daily_mean_lower_bound": summary[
            "daily_mean_one_sided_90pct_lower_bound"
        ]
        is not None
        and summary["daily_mean_one_sided_90pct_lower_bound"] > 0,
    }


def run_validation(database: Path, audit_path: Path):
    source = build_tape(database, audit_path)
    cfg = Experiment()
    decisions, rejections = select_decisions(source["tape"], CONFIGURATION, cfg)
    development = run_sizing(
        _normalize(decisions, "development"),
        "fixed_1",
        source["partition_days"]["development"],
        cfg,
    )
    if development["trade_ledger_sha256"] != EXPECTED_DEVELOPMENT_LEDGER:
        raise ValueError("Study 023 development replay does not reproduce Study 022 selection")
    validation = run_sizing(
        _normalize(decisions, "validation"),
        "fixed_1",
        source["partition_days"]["validation"],
        cfg,
    )
    aggregate = run_sizing(_normalize(decisions), "fixed_1", source["observed_days"], cfg)
    validation_checks = validation_gates(validation)
    aggregate_checks = aggregate_gates(aggregate)
    passed = all(validation_checks.values()) and all(aggregate_checks.values())
    risk_sizing = None
    risk_recommendation = None
    if passed:
        risk_sizing = {
            variant: run_sizing(_normalize(decisions), variant, source["observed_days"], cfg)
            for variant in RISK_VARIANTS
        }
        risk_recommendation = _risk_recommendation(risk_sizing)
    report = {
        "study": "023",
        "state": "complete_candidate" if passed else "complete_rejected",
        "registration": registration(),
        "registration_sha256": registration_hash(),
        "source": {
            "eligible_research_markets": source["eligible_markets"],
            "development_utc_dates": len(source["partition_days"]["development"]),
            "validation_utc_dates": len(source["partition_days"]["validation"]),
            "observed_utc_dates": len(source["observed_days"]),
            "holdout_markets": source["holdout_markets"],
            "holdout_evaluated": False,
        },
        "configuration": CONFIGURATION,
        "decision_rejections": dict(sorted(rejections.items())),
        "development_fixed_1": development,
        "development_reproduced": True,
        "validation_fixed_1": validation,
        "validation_gates": validation_checks,
        "aggregate_fixed_1": aggregate,
        "aggregate_gates": aggregate_checks,
        "complete_gate_passed": passed,
        "risk_sizing": risk_sizing,
        "risk_recommendation": risk_recommendation,
        "holdout": {"locked": True, "evaluated": False},
        "production_orders_authorized": False,
    }
    report["report_sha256"] = hashlib.sha256(canonical(report)).hexdigest()
    return report


def public_summary(report: dict):
    return {key: value for key, value in report.items() if key not in {"registration", "decision_rejections"}}
