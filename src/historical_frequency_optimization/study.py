from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from historical_backtest.screen import forecast, load_source
from historical_optimization.study import blend_probability
from historical_robust_optimization.registration import RISK_VARIANTS
from historical_robust_optimization.study import run_sizing
from research_lab.engine import entry_fee
from research_lab.settings import Experiment
from research_lab.storage import canonical

from .registration import (
    FAST_VARIANCE_WEIGHTS,
    TREND_MULTIPLIERS,
    configurations,
    registration,
    registration_hash,
)

NANOSECONDS = 1_000_000_000
STUDY_020_BASE_PNL = Decimal("24.4806")
STUDY_020_EX_TOP_THREE = Decimal("21.2847")
STUDY_020_TWO_CENT_STRESS = Decimal("9.2233")


@dataclass(frozen=True)
class Opportunity:
    ticker: str
    created_ns: int
    settled_ns: int
    settled_day: str
    partition: str
    block: int
    partition_block: int
    result: str
    seconds_left: int
    yes_bid: Decimal
    yes_ask: Decimal
    market_yes_probability: float
    fast_slow_variance_ratio: float
    model_yes_probabilities: dict[str, float]

    @property
    def no_ask(self):
        return Decimal(1) - self.yes_bid

    @property
    def spread(self):
        return self.yes_ask - self.yes_bid


def model_key(fast_weight: float, trend_multiplier: float) -> str:
    return f"{fast_weight:.2f}|{trend_multiplier:+.2f}"


def probability_for_model(fair: dict, fast_weight: float, trend_multiplier: float) -> float:
    variance = fast_weight * fair["fast_variance"] + (1 - fast_weight) * fair["slow_variance"]
    if variance <= 0:
        return 0.5
    sigma = fair["spot"] * math.sqrt(variance * fair["covariance_sum"]) / 60
    if sigma <= 0:
        return 0.5

    seconds_left = int(fair["seconds_left"])
    offsets = range(max(1, seconds_left - 59), seconds_left + 1)
    future_count = len(offsets)
    observed_sum = fair["expected_average"] * 60 - future_count * fair["spot"]
    drift_per_second = trend_multiplier * fair["trailing_60_second_log_return"] / 60
    future_sum = sum(fair["spot"] * math.exp(drift_per_second * offset) for offset in offsets)
    expected_average = (observed_sum + future_sum) / 60
    z_score = (expected_average - fair["threshold"]) / sigma
    probability = 0.5 * (1 + math.erf(z_score / math.sqrt(2)))
    return min(0.999, max(0.001, probability))


def build_tape(
    database: Path,
    audit_path: Path,
    partition_names: tuple[str, ...] = ("development", "validation"),
):
    allowed = {"development", "validation", "holdout"}
    if not partition_names or len(set(partition_names)) != len(partition_names):
        raise ValueError("partition_names must contain unique partition names")
    if not set(partition_names) <= allowed:
        raise ValueError("unknown Dataset 017 partition")
    partitions, candles, benchmark, exclusions = load_source(
        database,
        audit_path,
        include_holdout="holdout" in partition_names,
    )
    tagged = [
        (market, partition)
        for partition in partition_names
        for market in partitions[partition]
    ]
    tagged.sort(key=lambda value: (value[0].close_second, value[0].ticker))
    eligible = []
    excluded = Counter()
    for market, partition in tagged:
        reasons = [name for name, tickers in exclusions.items() if market.ticker in tickers]
        if market.ticker not in candles:
            reasons.append("missing_candle_history")
        if reasons:
            for reason in set(reasons):
                excluded[reason] += 1
            continue
        eligible.append((market, partition))

    partition_totals = Counter(partition for _market, partition in eligible)
    partition_seen = Counter()
    tape = []
    partition_days = {partition: set() for partition in partition_names}
    for index, (market, partition) in enumerate(eligible):
        block = min(4, index * 5 // len(eligible))
        partition_index = partition_seen[partition]
        partition_seen[partition] += 1
        partition_block = min(4, partition_index * 5 // partition_totals[partition])
        day = datetime.fromtimestamp(market.close_second, timezone.utc).date().isoformat()
        partition_days[partition].add(day)
        rows = []
        for quote in candles[market.ticker]:
            seconds_left = market.close_second - quote.second
            if not 5 <= seconds_left <= 300:
                continue
            fair = forecast(market, quote.second, benchmark, adaptive=True)
            if fair is None:
                continue
            past = benchmark.get(quote.second - 61)
            if past is None or past <= 0:
                continue
            fair = {**fair, "trailing_60_second_log_return": math.log(fair["spot"] / past)}
            probabilities = {
                model_key(fast, trend): probability_for_model(fair, fast, trend)
                for fast in FAST_VARIANCE_WEIGHTS
                for trend in TREND_MULTIPLIERS
            }
            ratio = fair["fast_variance"] / fair["slow_variance"]
            rows.append(
                Opportunity(
                    ticker=market.ticker,
                    created_ns=quote.second * NANOSECONDS,
                    settled_ns=market.close_second * NANOSECONDS,
                    settled_day=day,
                    partition=partition,
                    block=block,
                    partition_block=partition_block,
                    result=market.result,
                    seconds_left=seconds_left,
                    yes_bid=quote.yes_bid,
                    yes_ask=quote.yes_ask,
                    market_yes_probability=quote.midpoint,
                    fast_slow_variance_ratio=ratio,
                    model_yes_probabilities=probabilities,
                )
            )
        tape.append((market, rows))
    return {
        "tape": tape,
        "eligible_markets": len(eligible),
        "excluded_unique_markets": len(tagged) - len(eligible),
        "exclusion_memberships": dict(sorted(excluded.items())),
        "observed_days": sorted(set().union(*partition_days.values())),
        "partition_days": {key: sorted(value) for key, value in partition_days.items()},
        "holdout_markets": len(partitions["holdout"]),
        "benchmark_top_of_second_values_loaded": benchmark.loaded_seconds,
    }


def select_decisions(tape, parameters: dict, cfg: Experiment):
    decisions = []
    rejections = Counter()
    key = model_key(parameters["fast_variance_weight"], parameters["trend_multiplier"])
    market_weight = parameters["probability_market_log_odds_weight"]
    maximum_ratio = parameters["maximum_fast_slow_variance_ratio"]
    for _market, opportunities in tape:
        chosen = None
        for row in opportunities:
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


def _partition_decisions(decisions: list[dict], partition: str):
    return [{**row, "block": row["partition_block"]} for row in decisions if row["partition"] == partition]


def _trades_per_day(summary: dict) -> float:
    return summary["settled_markets"] / summary["observed_days"]


def _mean_price(summary: dict) -> Decimal | None:
    value = summary["entry_diagnostics"]["mean_entry_price"]
    return Decimal(value) if value is not None else None


def development_gates(summary: dict):
    trades_per_day = _trades_per_day(summary)
    price = _mean_price(summary)
    return {
        "average_8_to_12_trades_per_day": 8 <= trades_per_day <= 12,
        "minimum_65pct_win_rate": summary["win_rate"] is not None and summary["win_rate"] >= 0.65,
        "mean_entry_price_45_to_72_cents": price is not None
        and Decimal("0.45") <= price <= Decimal("0.72"),
        "base_pnl_above_15": Decimal(summary["realized_net_pnl"]) > 15,
        "pnl_without_top_three_above_10": Decimal(summary["pnl_without_top_three_winners"]) > 10,
        "positive_one_cent_stress": Decimal(summary["stressed_pnl"]["1"]) > 0,
        "positive_two_cent_stress": Decimal(summary["stressed_pnl"]["2"]) > 0,
        "positive_on_majority_of_days": summary["positive_day_share"] is not None
        and summary["positive_day_share"] > 0.5,
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


def validation_gates(summary: dict):
    trades_per_day = _trades_per_day(summary)
    price = _mean_price(summary)
    return {
        "average_8_to_12_trades_per_day": 8 <= trades_per_day <= 12,
        "minimum_65pct_win_rate": summary["win_rate"] is not None and summary["win_rate"] >= 0.65,
        "mean_entry_price_45_to_72_cents": price is not None
        and Decimal("0.45") <= price <= Decimal("0.72"),
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
    return {
        "base_pnl_exceeds_study_020": Decimal(summary["realized_net_pnl"]) > STUDY_020_BASE_PNL,
        "pnl_without_top_three_exceeds_study_020": Decimal(
            summary["pnl_without_top_three_winners"]
        )
        > STUDY_020_EX_TOP_THREE,
        "two_cent_stress_exceeds_study_020": Decimal(summary["stressed_pnl"]["2"])
        > STUDY_020_TWO_CENT_STRESS,
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


def _ranking_key(row):
    summary = row["development_fixed_1"]
    passed = sum(row["development_gates"].values())
    return (
        row["development_gate_passed"],
        passed,
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
    development_tape = [row for row in source["tape"] if row[1] and row[1][0].partition == "development"]
    rows = []
    grid = configurations()
    for index, parameters in enumerate(grid, start=1):
        decisions, rejections = select_decisions(development_tape, parameters, cfg)
        normalized = [{**row, "block": row["partition_block"]} for row in decisions]
        summary = run_sizing(normalized, "fixed_1", source["partition_days"]["development"], cfg)
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
            _partition_decisions(decisions, "development"),
            "fixed_1",
            source["partition_days"]["development"],
            cfg,
        )
        validation = run_sizing(
            _partition_decisions(decisions, "validation"),
            "fixed_1",
            source["partition_days"]["validation"],
            cfg,
        )
        aggregate = run_sizing(decisions, "fixed_1", source["observed_days"], cfg)
        validation_checks = validation_gates(validation)
        aggregate_checks = aggregate_gates(aggregate)
        complete_pass = (
            all(selected["development_gates"].values())
            and all(validation_checks.values())
            and all(aggregate_checks.values())
        )
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
                variant: run_sizing(decisions, variant, source["observed_days"], cfg)
                for variant in RISK_VARIANTS
            }
            risk_recommendation = _risk_recommendation(risk_sizing)

    family_leaders = {}
    for trend in TREND_MULTIPLIERS:
        family = [row for row in ranked if row["configuration"]["trend_multiplier"] == trend]
        family_leaders[f"trend_{trend:+.2f}"] = family[0] if family else None

    complete_pass = bool(selected_result and selected_result["complete_gate_passed"])
    report = {
        "study": "021",
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
        "holdout": {
            "locked": True,
            "evaluated": False,
            "reason": "Study 021 is development-only",
        },
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
