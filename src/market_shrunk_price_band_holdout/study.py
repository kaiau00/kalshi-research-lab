from __future__ import annotations

import hashlib
from collections import Counter
from decimal import Decimal
from pathlib import Path

from historical_frequency_optimization.study import build_tape
from historical_market_confirmation.kelly import run_variant
from historical_market_confirmation.kelly_registration import SIGNAL
from historical_market_confirmation.study import _normalize, select_decisions
from research_lab.settings import Experiment
from research_lab.storage import canonical

from .registration import (
    EXCLUDED_PRICE_MAXIMUM_EXCLUSIVE,
    EXCLUDED_PRICE_MINIMUM,
    EXPECTED_FILTERED_UNSEALED_LEDGER,
    EXPECTED_STUDY_023_LEDGER,
    registration,
    registration_hash,
)


def filter_candidate(decisions: list[dict]):
    lower = Decimal(EXCLUDED_PRICE_MINIMUM)
    upper = Decimal(EXCLUDED_PRICE_MAXIMUM_EXCLUSIVE)
    kept = []
    rejections = Counter()
    for decision in decisions:
        if lower <= decision["price"] < upper:
            rejections["excluded_65_to_69_cent_first_signal"] += 1
        else:
            kept.append(decision)
    return kept, dict(sorted(rejections.items()))


def holdout_gates(summary: dict):
    observed_days = summary["observed_days"]
    trades_per_day = summary["trades"] / observed_days if observed_days else 0
    return {
        "minimum_100_settled_trades": summary["trades"] >= 100,
        "minimum_20_observed_utc_dates": observed_days >= 20,
        "minimum_3_trades_per_observed_day": trades_per_day >= 3,
        "minimum_65pct_win_rate": summary["win_rate"] is not None
        and summary["win_rate"] >= 0.65,
        "positive_net_pnl": Decimal(summary["net_pnl"]) > 0,
        "positive_pnl_without_top_three": Decimal(
            summary["pnl_without_top_three_winners"]
        )
        > 0,
        "positive_one_cent_stress": Decimal(summary["stressed_pnl"]["1"]) > 0,
        "positive_two_cent_stress": Decimal(summary["stressed_pnl"]["2"]) > 0,
        "positive_on_majority_of_days": summary["positive_day_share"] is not None
        and summary["positive_day_share"] > 0.5,
        "positive_in_four_of_five_base_blocks": summary["positive_blocks"] >= 4,
        "positive_two_cent_stress_in_four_of_five_blocks": summary[
            "positive_two_cent_stressed_blocks"
        ]
        >= 4,
        "maximum_drawdown_at_most_5": Decimal(summary["maximum_drawdown"]) <= 5,
        "positive_one_sided_90pct_daily_mean_lower_bound": summary[
            "daily_mean_one_sided_90pct_lower_bound"
        ]
        is not None
        and summary["daily_mean_one_sided_90pct_lower_bound"] > 0,
    }


def run_study(database: Path, audit_path: Path, *, unlock_holdout: bool = False):
    if not unlock_holdout:
        raise ValueError("Study 026 holdout is sealed; explicit --unlock-holdout authorization is required")

    cfg = Experiment()
    unsealed = build_tape(database, audit_path)
    original_decisions, _ = select_decisions(unsealed["tape"], SIGNAL, cfg)
    original_decisions = _normalize(original_decisions)
    original = run_variant(original_decisions, "fixed_1", unsealed["observed_days"], cfg)
    if original["trade_ledger_sha256"] != EXPECTED_STUDY_023_LEDGER:
        raise ValueError("Study 026 does not reproduce Study 023 before holdout disclosure")
    filtered_unsealed, _ = filter_candidate(original_decisions)
    filtered_replay = run_variant(filtered_unsealed, "fixed_1", unsealed["observed_days"], cfg)
    if filtered_replay["trade_ledger_sha256"] != EXPECTED_FILTERED_UNSEALED_LEDGER:
        raise ValueError("Study 026 candidate does not reproduce its frozen unsealed ledger")

    holdout = build_tape(database, audit_path, partition_names=("holdout",))
    holdout_decisions, base_rejections = select_decisions(holdout["tape"], SIGNAL, cfg)
    candidate_decisions, filter_rejections = filter_candidate(
        _normalize(holdout_decisions, "holdout")
    )
    result = run_variant(candidate_decisions, "fixed_1", holdout["observed_days"], cfg)
    gates = holdout_gates(result)
    report = {
        "study": "026",
        "state": "complete_holdout_passed" if all(gates.values()) else "complete_holdout_rejected",
        "registration": registration(),
        "registration_sha256": registration_hash(),
        "source": {
            "eligible_holdout_markets": holdout["eligible_markets"],
            "excluded_holdout_markets": holdout["excluded_unique_markets"],
            "holdout_utc_dates": len(holdout["observed_days"]),
            "holdout_disclosed": True,
        },
        "replay_guards": {
            "study_023_trade_ledger_sha256": original["trade_ledger_sha256"],
            "filtered_unsealed_trade_ledger_sha256": filtered_replay["trade_ledger_sha256"],
        },
        "base_signal_rejections": dict(sorted(base_rejections.items())),
        "candidate_filter_rejections": filter_rejections,
        "holdout_fixed_1": result,
        "holdout_gates": gates,
        "all_holdout_gates_passed": all(gates.values()),
        "risk_sizing_opened": False,
        "production_orders_authorized": False,
        "production_change_authorized": False,
    }
    report["report_sha256"] = hashlib.sha256(canonical(report)).hexdigest()
    return report


def public_summary(report: dict):
    return {
        key: value
        for key, value in report.items()
        if key not in {"registration", "base_signal_rejections"}
    }
