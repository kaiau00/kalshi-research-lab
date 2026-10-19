from __future__ import annotations

import hashlib
from collections import Counter
from decimal import Decimal
from pathlib import Path

from historical_frequency_optimization.study import (
    aggregate_gates,
    build_tape,
    development_gates,
    model_key,
    validation_gates,
)
from historical_optimization.study import blend_probability
from historical_robust_optimization.registration import RISK_VARIANTS
from historical_robust_optimization.study import run_sizing
from research_lab.engine import entry_fee
from research_lab.settings import Experiment
from research_lab.storage import canonical

from .registration import QUOTE_CONFIRMATIONS, configurations, registration, registration_hash


def quote_confirmation_passes(mode: str, side: str, previous_midpoint: float | None, midpoint: float):
    if mode == "none":
        return True
    if previous_midpoint is None:
        return False
    selected_side_move = midpoint - previous_midpoint
    if side == "no":
        selected_side_move = -selected_side_move
    if mode == "nonnegative_selected_side_move":
        return selected_side_move >= 0
    if mode == "one_cent_selected_side_move":
        return selected_side_move >= 0.01
    raise ValueError(f"unknown quote confirmation: {mode}")


def select_decisions(tape, parameters: dict, cfg: Experiment):
    decisions = []
    rejections = Counter()
    key = model_key(parameters["fast_variance_weight"], 0.0)
    market_weight = parameters["probability_market_log_odds_weight"]
    maximum_ratio = parameters["maximum_fast_slow_variance_ratio"]
    confirmation = parameters["quote_confirmation"]
    for _market, opportunities in tape:
        chosen = None
        previous_midpoint = None
        for row in opportunities:
            prior_midpoint = previous_midpoint
            previous_midpoint = row.market_yes_probability
            if not parameters["minimum_seconds_left"] <= row.seconds_left <= parameters["maximum_seconds_left"]:
                continue
            if maximum_ratio is not None and row.fast_slow_variance_ratio > maximum_ratio:
                rejections["fast_slow_variance_ratio"] += 1
                continue
            raw_yes = row.model_yes_probabilities[key]
            blended_yes = blend_probability(raw_yes, row.market_yes_probability, market_weight)
            candidates = []
            for side in ("yes", "no"):
                price = row.yes_ask if side == "yes" else row.no_ask
                probability = blended_yes if side == "yes" else 1 - blended_yes
                edge = probability - float(price + entry_fee(price, 1, cfg))
                candidates.append((edge, side, price, probability))
            edge, side, price, probability = max(
                candidates, key=lambda value: (value[0], value[1] == "yes")
            )
            if not quote_confirmation_passes(
                confirmation, side, prior_midpoint, row.market_yes_probability
            ):
                rejections["quote_confirmation"] += 1
                continue
            if edge < parameters["minimum_net_edge"]:
                rejections["minimum_net_edge"] += 1
                continue
            if not Decimal(str(parameters["minimum_selected_ask"])) <= price < Decimal(
                str(parameters["maximum_selected_ask_exclusive"])
            ):
                rejections["selected_ask_band"] += 1
                continue
            if abs(raw_yes - row.market_yes_probability) > parameters["maximum_raw_model_market_gap"]:
                rejections["raw_model_market_gap"] += 1
                continue
            if row.spread > Decimal(str(parameters["maximum_binary_spread"])):
                rejections["binary_spread"] += 1
                continue
            stressed_price = price + Decimal("0.02")
            if stressed_price >= 1:
                rejections["invalid_stressed_price"] += 1
                continue
            stressed_edge = probability - float(stressed_price + entry_fee(stressed_price, 1, cfg))
            if stressed_edge < parameters["minimum_two_cent_stressed_edge"]:
                rejections["minimum_two_cent_stressed_edge"] += 1
                continue
            chosen = {
                "ticker": row.ticker,
                "created_ns": row.created_ns,
                "settled_ns": row.settled_ns,
                "settled_day": row.settled_day,
                "partition": row.partition,
                "block": row.block,
                "partition_block": row.partition_block,
                "result": row.result,
                "side": side,
                "price": price,
                "probability": probability,
                "raw_yes_probability": raw_yes,
                "market_yes_probability": row.market_yes_probability,
                "previous_market_yes_probability": prior_midpoint,
                "seconds_left": row.seconds_left,
                "edge": edge,
                "fast_slow_variance_ratio": row.fast_slow_variance_ratio,
            }
            break
        if chosen is None:
            rejections["no_qualifying_decision"] += 1
        else:
            decisions.append(chosen)
    return decisions, rejections


def _normalize(decisions: list[dict], partition: str | None = None):
    return [
        {**row, "block": row["partition_block"] if partition is not None else row["block"]}
        for row in decisions
        if partition is None or row["partition"] == partition
    ]


def _trades_per_day(summary: dict):
    return summary["settled_markets"] / summary["observed_days"]


def _ranking_key(row):
    summary = row["development_fixed_1"]
    return (
        row["development_gate_passed"],
        sum(row["development_gates"].values()),
        Decimal(summary["minimum_two_cent_stressed_block_pnl"]),
        Decimal(summary["stressed_pnl"]["2"]),
        Decimal(summary["pnl_without_top_three_winners"]),
        -abs(_trades_per_day(summary) - 10),
        -Decimal(summary["maximum_drawdown"]),
    )


def _risk_recommendation(sizing: dict):
    eligible = []
    for name, summary in sizing.items():
        drawdown = Decimal(summary["maximum_drawdown"])
        stress = Decimal(summary["stressed_pnl"]["2"])
        ex_top = Decimal(summary["pnl_without_top_three_winners"])
        if stress > 0 and ex_top > 0 and drawdown <= 10:
            ratio = stress / drawdown if drawdown > 0 else Decimal("Infinity")
            eligible.append((ratio, stress, -drawdown, name))
    eligible.sort(reverse=True)
    return eligible[0][-1] if eligible else None


def run_study(database: Path, audit_path: Path, progress=None):
    source = build_tape(database, audit_path)
    cfg = Experiment()
    development_tape = [
        row for row in source["tape"] if row[1] and row[1][0].partition == "development"
    ]
    rows = []
    grid = configurations()
    for index, parameters in enumerate(grid, start=1):
        decisions, rejections = select_decisions(development_tape, parameters, cfg)
        summary = run_sizing(
            _normalize(decisions, "development"),
            "fixed_1",
            source["partition_days"]["development"],
            cfg,
        )
        gates = development_gates(summary)
        rows.append(
            {
                "configuration": parameters,
                "development_rejections": dict(sorted(rejections.items())),
                "development_fixed_1": summary,
                "development_gates": gates,
                "development_gate_passed": all(gates.values()),
            }
        )
        if progress and (index == 1 or index % 250 == 0 or index == len(grid)):
            progress(index, len(grid))

    ranked = sorted(rows, key=lambda row: row["configuration"]["name"])
    ranked.sort(key=_ranking_key, reverse=True)
    eligible = [row for row in ranked if row["development_gate_passed"]]
    selected = eligible[0] if eligible else None
    selected_result = None
    risk_sizing = None
    risk_recommendation = None
    if selected:
        decisions, rejections = select_decisions(source["tape"], selected["configuration"], cfg)
        development = run_sizing(
            _normalize(decisions, "development"),
            "fixed_1",
            source["partition_days"]["development"],
            cfg,
        )
        validation = run_sizing(
            _normalize(decisions, "validation"),
            "fixed_1",
            source["partition_days"]["validation"],
            cfg,
        )
        aggregate = run_sizing(
            _normalize(decisions), "fixed_1", source["observed_days"], cfg
        )
        validation_checks = validation_gates(validation)
        aggregate_checks = aggregate_gates(aggregate)
        complete_pass = all(validation_checks.values()) and all(aggregate_checks.values())
        selected_result = {
            "configuration": selected["configuration"],
            "all_decision_rejections": dict(sorted(rejections.items())),
            "development_fixed_1": development,
            "development_gates": selected["development_gates"],
            "validation_fixed_1": validation,
            "validation_gates": validation_checks,
            "aggregate_fixed_1": aggregate,
            "aggregate_gates": aggregate_checks,
            "complete_gate_passed": complete_pass,
        }
        if complete_pass:
            risk_sizing = {
                variant: run_sizing(_normalize(decisions), variant, source["observed_days"], cfg)
                for variant in RISK_VARIANTS
            }
            risk_recommendation = _risk_recommendation(risk_sizing)

    family_leaders = {}
    for confirmation in QUOTE_CONFIRMATIONS:
        family = [row for row in ranked if row["configuration"]["quote_confirmation"] == confirmation]
        family_leaders[confirmation] = family[0] if family else None

    complete_pass = bool(selected_result and selected_result["complete_gate_passed"])
    report = {
        "study": "022",
        "state": (
            "complete_candidate" if complete_pass else "complete_validation_rejected"
            if selected_result
            else "complete_no_development_signal"
        ),
        "registration": registration(),
        "registration_sha256": registration_hash(),
        "source": {
            "eligible_research_markets": source["eligible_markets"],
            "excluded_unique_markets": source["excluded_unique_markets"],
            "exclusion_memberships": source["exclusion_memberships"],
            "development_utc_dates": len(source["partition_days"]["development"]),
            "validation_utc_dates": len(source["partition_days"]["validation"]),
            "observed_utc_dates": len(source["observed_days"]),
            "holdout_markets": source["holdout_markets"],
            "holdout_evaluated": False,
            "benchmark_top_of_second_values_loaded": source[
                "benchmark_top_of_second_values_loaded"
            ],
        },
        "configurations_evaluated": len(rows),
        "development_gate_passers": len(eligible),
        "selected_result": selected_result,
        "risk_sizing": risk_sizing,
        "risk_recommendation": risk_recommendation,
        "family_leaders": family_leaders,
        "top_diagnostic_configurations": ranked[:20],
        "all_configurations": sorted(rows, key=lambda row: row["configuration"]["name"]),
        "holdout": {"locked": True, "evaluated": False, "reason": "Study 022 is development-only"},
        "production_orders_authorized": False,
    }
    report["report_sha256"] = hashlib.sha256(canonical(report)).hexdigest()
    return report


def public_summary(report: dict):
    return {
        "study": report["study"],
        "state": report["state"],
        "registration_sha256": report["registration_sha256"],
        "report_sha256": report["report_sha256"],
        "source": report["source"],
        "configurations_evaluated": report["configurations_evaluated"],
        "development_gate_passers": report["development_gate_passers"],
        "selected_result": report["selected_result"],
        "risk_sizing": report["risk_sizing"],
        "risk_recommendation": report["risk_recommendation"],
        "family_leaders": report["family_leaders"],
        "top_diagnostic_configurations": report["top_diagnostic_configurations"][:5],
        "holdout": report["holdout"],
        "production_orders_authorized": False,
    }
