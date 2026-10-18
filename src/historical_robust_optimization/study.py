from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from historical_backtest.screen import forecast, load_source
from historical_optimization.study import blend_probability, full_kelly_fraction
from research_lab.engine import entry_fee
from research_lab.settings import Experiment
from research_lab.storage import canonical

from .registration import (
    FAST_VARIANCE_WEIGHTS,
    RISK_VARIANTS,
    configurations,
    registration,
    registration_hash,
)

NANOSECONDS = 1_000_000_000
STARTING_CASH = Decimal("100.00")
MAX_KELLY_BUDGET = Decimal("3.00")
STUDY_019_BASE_PNL = Decimal("11.9751")
STUDY_019_EX_TOP_THREE = Decimal("10.5276")
STUDY_019_TWO_CENT_STRESS = Decimal("1.3466")


@dataclass(frozen=True)
class Opportunity:
    ticker: str
    created_ns: int
    settled_ns: int
    settled_day: str
    partition: str
    block: int
    result: str
    seconds_left: int
    yes_bid: Decimal
    yes_ask: Decimal
    market_yes_probability: float
    raw_yes_probabilities: dict[str, float]

    @property
    def no_ask(self):
        return Decimal(1) - self.yes_bid

    @property
    def spread(self):
        return self.yes_ask - self.yes_bid


def probability_for_variance_weight(fair: dict, fast_weight: float) -> float:
    fast = fair["fast_variance"]
    slow = fair["slow_variance"]
    variance = fast_weight * fast + (1 - fast_weight) * slow
    if variance <= 0:
        return 0.5
    sigma = fair["spot"] * math.sqrt(variance * fair["covariance_sum"]) / 60
    if sigma <= 0:
        return 0.5
    z_score = (fair["expected_average"] - fair["threshold"]) / sigma
    probability = 0.5 * (1 + math.erf(z_score / math.sqrt(2)))
    return min(0.999, max(0.001, probability))


def build_tape(database: Path, audit_path: Path):
    partitions, candles, benchmark, exclusions = load_source(database, audit_path)
    tagged = [
        (market, partition)
        for partition in ("development", "validation")
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
    tape = []
    partition_days = {"development": set(), "validation": set()}
    for index, (market, partition) in enumerate(eligible):
        block = min(4, index * 5 // len(eligible))
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
            probabilities = {
                f"{weight:.2f}": probability_for_variance_weight(fair, weight)
                for weight in FAST_VARIANCE_WEIGHTS
            }
            rows.append(
                Opportunity(
                    ticker=market.ticker,
                    created_ns=quote.second * NANOSECONDS,
                    settled_ns=market.close_second * NANOSECONDS,
                    settled_day=day,
                    partition=partition,
                    block=block,
                    result=market.result,
                    seconds_left=seconds_left,
                    yes_bid=quote.yes_bid,
                    yes_ask=quote.yes_ask,
                    market_yes_probability=quote.midpoint,
                    raw_yes_probabilities=probabilities,
                )
            )
        tape.append((market, rows))
    return {
        "tape": tape,
        "benchmark": benchmark,
        "eligible_markets": len(eligible),
        "excluded_unique_markets": len(tagged) - len(eligible),
        "exclusion_memberships": dict(sorted(excluded.items())),
        "observed_days": sorted(partition_days["development"] | partition_days["validation"]),
        "partition_days": {
            key: sorted(value) for key, value in partition_days.items()
        },
        "holdout_markets": len(partitions["holdout"]),
    }


def select_decisions(tape, parameters: dict, cfg: Experiment):
    decisions = []
    rejections = Counter()
    probability_key = f'{parameters["fast_variance_weight"]:.2f}'
    market_weight = parameters["probability_market_log_odds_weight"]
    for _market, opportunities in tape:
        chosen = None
        for row in opportunities:
            if not (
                parameters["minimum_seconds_left"]
                <= row.seconds_left
                <= parameters["maximum_seconds_left"]
            ):
                continue
            raw_yes = row.raw_yes_probabilities[probability_key]
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
            if not (
                Decimal(str(parameters["minimum_selected_ask"]))
                <= price
                < Decimal(str(parameters["maximum_selected_ask_exclusive"]))
            ):
                rejections["selected_ask_band"] += 1
                continue
            if (
                abs(raw_yes - row.market_yes_probability)
                > parameters["maximum_raw_model_market_gap"]
            ):
                rejections["raw_model_market_gap"] += 1
                continue
            if row.spread > Decimal(str(parameters["maximum_binary_spread"])):
                rejections["binary_spread"] += 1
                continue
            stressed_price = price + Decimal("0.02")
            if stressed_price >= 1:
                rejections["invalid_stressed_price"] += 1
                continue
            stressed_edge = probability - float(
                stressed_price + entry_fee(stressed_price, 1, cfg)
            )
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
                "result": row.result,
                "side": side,
                "price": price,
                "probability": probability,
                "raw_yes_probability": raw_yes,
                "market_yes_probability": row.market_yes_probability,
                "seconds_left": row.seconds_left,
                "edge": edge,
            }
            break
        if chosen is None:
            rejections["no_qualifying_decision"] += 1
        else:
            decisions.append(chosen)
    return decisions, rejections


def _quantity(price: Decimal, budget: Decimal, cash: Decimal, cfg: Experiment) -> int:
    budget = min(budget, cash)
    if budget <= 0 or not 0 < price < 1:
        return 0
    count = int(budget / price)
    while count and price * count + entry_fee(price, count, cfg) > budget:
        count -= 1
    return count


def _budget(variant: str, probability: float, price: Decimal, cash: Decimal, cfg: Experiment):
    settings = RISK_VARIANTS[variant]
    if settings["kind"] == "fixed":
        return min(Decimal(settings["maximum_all_in_dollars"]), cash), None
    unit_cost = price + entry_fee(price, 1, cfg)
    kelly = full_kelly_fraction(probability, unit_cost)
    target = min(
        MAX_KELLY_BUDGET,
        cash * kelly * Decimal(settings["multiplier"]),
        cash,
    )
    return target, kelly


def _stress_pnl(trade: dict, cents: int, cfg: Experiment):
    price = min(Decimal("0.999999"), trade["price"] + Decimal(cents) / 100)
    return trade["payout"] - price * trade["quantity"] - entry_fee(
        price, trade["quantity"], cfg
    )


def run_sizing(decisions: list[dict], variant: str, observed_days: list[str], cfg: Experiment):
    cash = STARTING_CASH
    peak = STARTING_CASH
    maximum_drawdown = Decimal(0)
    zero_size = Counter()
    target_budgets = []
    kelly_cap_binding_decisions = 0
    trades = []
    for decision in decisions:
        budget, kelly = _budget(variant, decision["probability"], decision["price"], cash, cfg)
        target_budgets.append(budget)
        if kelly is not None and budget == MAX_KELLY_BUDGET:
            kelly_cap_binding_decisions += 1
        quantity = _quantity(decision["price"], budget, cash, cfg)
        if quantity < 1:
            reason = "kelly_target_below_one_contract" if kelly is not None else "cash_below_one_contract"
            zero_size[reason] += 1
            continue
        fee = entry_fee(decision["price"], quantity, cfg)
        cost = decision["price"] * quantity + fee
        won = decision["side"] == decision["result"]
        payout = Decimal(quantity if won else 0)
        pnl = payout - cost
        cash += pnl
        peak = max(peak, cash)
        maximum_drawdown = max(maximum_drawdown, peak - cash)
        trades.append(
            {
                **decision,
                "quantity": quantity,
                "fee": fee,
                "cost": cost,
                "payout": payout,
                "pnl": pnl,
                "won": won,
                "target_budget": budget,
                "full_kelly_fraction": kelly,
            }
        )
    pnls = [row["pnl"] for row in trades]
    pnl = sum(pnls, Decimal(0))
    winners = sorted((value for value in pnls if value > 0), reverse=True)
    stress = {
        str(cents): sum((_stress_pnl(row, cents, cfg) for row in trades), Decimal(0))
        for cents in (1, 2)
    }
    daily = {day: Decimal(0) for day in observed_days}
    blocks = [Decimal(0) for _ in range(5)]
    stressed_blocks = {str(cents): [Decimal(0) for _ in range(5)] for cents in (1, 2)}
    for trade in trades:
        daily[trade["settled_day"]] += trade["pnl"]
        blocks[trade["block"]] += trade["pnl"]
        for cents in (1, 2):
            stressed_blocks[str(cents)][trade["block"]] += _stress_pnl(trade, cents, cfg)
    daily_values = [float(value) for value in daily.values()]
    daily_mean = sum(daily_values) / len(daily_values) if daily_values else None
    if len(daily_values) > 1:
        variance = sum((value - daily_mean) ** 2 for value in daily_values) / (
            len(daily_values) - 1
        )
        standard_error = math.sqrt(variance / len(daily_values))
        lower_90 = daily_mean - 1.6448536269514722 * standard_error
    else:
        standard_error = None
        lower_90 = None
    entry_prices = [row["price"] for row in trades]
    return {
        "decisions": len(decisions),
        "settled_markets": len(trades),
        "wins": sum(row["won"] for row in trades),
        "win_rate": sum(row["won"] for row in trades) / len(trades) if trades else None,
        "contracts": sum(row["quantity"] for row in trades),
        "fees": str(sum((row["fee"] for row in trades), Decimal(0))),
        "realized_net_pnl": str(pnl),
        "ending_cash": str(cash),
        "pnl_without_top_three_winners": str(pnl - sum(winners[:3], Decimal(0))),
        "stressed_pnl": {key: str(value) for key, value in stress.items()},
        "maximum_drawdown": str(maximum_drawdown),
        "positive_day_share": (
            sum(value > 0 for value in daily.values()) / len(daily) if daily else None
        ),
        "positive_days": sum(value > 0 for value in daily.values()),
        "observed_days": len(observed_days),
        "mean_daily_pnl": daily_mean,
        "daily_pnl_standard_error": standard_error,
        "daily_mean_one_sided_90pct_lower_bound": lower_90,
        "block_pnl": [str(value) for value in blocks],
        "positive_blocks": sum(value > 0 for value in blocks),
        "stressed_block_pnl": {
            key: [str(value) for value in values] for key, values in stressed_blocks.items()
        },
        "positive_two_cent_stressed_blocks": sum(
            value > 0 for value in stressed_blocks["2"]
        ),
        "minimum_two_cent_stressed_block_pnl": str(min(stressed_blocks["2"])),
        "zero_size_decisions": dict(sorted(zero_size.items())),
        "kelly_cap_binding_decisions": (
            kelly_cap_binding_decisions
            if RISK_VARIANTS[variant]["kind"] == "fractional_kelly"
            else None
        ),
        "mean_target_budget": (
            str(sum(target_budgets, Decimal(0)) / len(target_budgets))
            if target_budgets
            else None
        ),
        "entry_diagnostics": {
            "minimum_entry_price": str(min(entry_prices)) if entry_prices else None,
            "mean_entry_price": (
                str(sum(entry_prices, Decimal(0)) / len(entry_prices)) if entry_prices else None
            ),
            "maximum_entry_price": str(max(entry_prices)) if entry_prices else None,
        },
        "trade_ledger_sha256": hashlib.sha256(
            canonical(
                [
                    {
                        "ticker": row["ticker"],
                        "side": row["side"],
                        "price": str(row["price"]),
                        "quantity": row["quantity"],
                        "pnl": str(row["pnl"]),
                    }
                    for row in trades
                ]
            )
        ).hexdigest(),
    }


def _gates(aggregate: dict, development: dict, validation: dict):
    return {
        "minimum_200_settlements": aggregate["settled_markets"] >= 200,
        "base_pnl_exceeds_study_019": Decimal(aggregate["realized_net_pnl"]) > STUDY_019_BASE_PNL,
        "pnl_without_top_three_exceeds_study_019": Decimal(
            aggregate["pnl_without_top_three_winners"]
        )
        > STUDY_019_EX_TOP_THREE,
        "two_cent_stress_exceeds_study_019": Decimal(aggregate["stressed_pnl"]["2"])
        > STUDY_019_TWO_CENT_STRESS,
        "positive_one_cent_stress": Decimal(aggregate["stressed_pnl"]["1"]) > 0,
        "positive_on_majority_of_days": aggregate["positive_day_share"] is not None
        and aggregate["positive_day_share"] > 0.5,
        "positive_in_four_of_five_base_blocks": aggregate["positive_blocks"] >= 4,
        "positive_two_cent_stress_in_four_of_five_blocks": aggregate[
            "positive_two_cent_stressed_blocks"
        ]
        >= 4,
        "maximum_drawdown_at_most_10": Decimal(aggregate["maximum_drawdown"]) <= 10,
        "positive_one_sided_90pct_daily_mean_lower_bound": aggregate[
            "daily_mean_one_sided_90pct_lower_bound"
        ]
        is not None
        and aggregate["daily_mean_one_sided_90pct_lower_bound"] > 0,
        "development_positive_base": Decimal(development["realized_net_pnl"]) > 0,
        "development_positive_ex_top_three": Decimal(
            development["pnl_without_top_three_winners"]
        )
        > 0,
        "development_positive_two_cent_stress": Decimal(development["stressed_pnl"]["2"]) > 0,
        "minimum_75_validation_settlements": validation["settled_markets"] >= 75,
        "validation_positive_base": Decimal(validation["realized_net_pnl"]) > 0,
        "validation_positive_ex_top_three": Decimal(
            validation["pnl_without_top_three_winners"]
        )
        > 0,
        "validation_positive_two_cent_stress": Decimal(validation["stressed_pnl"]["2"]) > 0,
    }


def _ranking_key(row):
    aggregate = row["fixed_1"]
    validation = row["original_validation"]
    return (
        row["stronger_gate_passed"],
        Decimal(aggregate["minimum_two_cent_stressed_block_pnl"]),
        Decimal(validation["stressed_pnl"]["2"]),
        Decimal(aggregate["stressed_pnl"]["2"]),
        Decimal(aggregate["pnl_without_top_three_winners"]),
        -Decimal(aggregate["maximum_drawdown"]),
    )


def _risk_recommendation(sizing: dict):
    eligible = []
    for name, summary in sizing.items():
        drawdown = Decimal(summary["maximum_drawdown"])
        stress = Decimal(summary["stressed_pnl"]["2"])
        gates = {
            "positive_two_cent_stress": stress > 0,
            "positive_without_top_three_winners": Decimal(
                summary["pnl_without_top_three_winners"]
            )
            > 0,
            "maximum_drawdown_at_most_10": drawdown <= 10,
        }
        summary["recommendation_gates"] = gates
        if all(gates.values()):
            ratio = stress / drawdown if drawdown > 0 else Decimal("Infinity")
            eligible.append((ratio, stress, -drawdown, -Decimal(summary["mean_target_budget"]), name))
    eligible.sort(reverse=True)
    return eligible[0][-1] if eligible else None


def run_study(database: Path, audit_path: Path):
    source = build_tape(database, audit_path)
    cfg = Experiment()
    rows = []
    for parameters in configurations():
        decisions, rejections = select_decisions(source["tape"], parameters, cfg)
        aggregate = run_sizing(decisions, "fixed_1", source["observed_days"], cfg)
        development = run_sizing(
            [row for row in decisions if row["partition"] == "development"],
            "fixed_1",
            source["partition_days"]["development"],
            cfg,
        )
        validation = run_sizing(
            [row for row in decisions if row["partition"] == "validation"],
            "fixed_1",
            source["partition_days"]["validation"],
            cfg,
        )
        gates = _gates(aggregate, development, validation)
        rows.append(
            {
                "configuration": parameters,
                "decision_rejections": dict(sorted(rejections.items())),
                "fixed_1": aggregate,
                "original_development": development,
                "original_validation": validation,
                "gates": gates,
                "stronger_gate_passed": all(gates.values()),
            }
        )
    ranked = sorted(rows, key=lambda row: row["configuration"]["name"])
    ranked.sort(key=_ranking_key, reverse=True)
    eligible = [row for row in ranked if row["stronger_gate_passed"]]
    selected = eligible[0] if eligible else None
    risk_sizing = None
    risk_recommendation = None
    if selected:
        decisions, _ = select_decisions(source["tape"], selected["configuration"], cfg)
        risk_sizing = {
            variant: run_sizing(decisions, variant, source["observed_days"], cfg)
            for variant in RISK_VARIANTS
        }
        risk_recommendation = _risk_recommendation(risk_sizing)
    report = {
        "study": "020",
        "state": "complete" if selected else "complete_no_stronger_signal",
        "registration": registration(),
        "registration_sha256": registration_hash(),
        "source": {
            "eligible_research_markets": source["eligible_markets"],
            "excluded_unique_markets": source["excluded_unique_markets"],
            "exclusion_memberships": source["exclusion_memberships"],
            "observed_utc_dates": len(source["observed_days"]),
            "holdout_markets": source["holdout_markets"],
            "holdout_evaluated": False,
            "benchmark_top_of_second_values_loaded": source["benchmark"].loaded_seconds,
        },
        "configurations_evaluated": len(rows),
        "stronger_signal_gate_passers": len(eligible),
        "selected_signal": selected,
        "risk_sizing": risk_sizing,
        "risk_recommendation": risk_recommendation,
        "top_diagnostic_configurations": ranked[:50],
        "all_configuration_summaries": sorted(rows, key=lambda row: row["configuration"]["name"]),
        "holdout": {
            "locked": True,
            "evaluated": False,
            "reason": "Study 020 is development-only",
        },
        "production_orders_authorized": False,
    }
    report["report_sha256"] = hashlib.sha256(canonical(report)).hexdigest()
    return report
