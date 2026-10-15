from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from historical_backtest.screen import forecast, load_source
from research_lab.engine import entry_fee
from research_lab.settings import Experiment
from research_lab.storage import canonical

from .registration import SIZING_VARIANTS, configurations, registration, registration_hash

NANOSECONDS = 1_000_000_000
STARTING_CASH = Decimal("100.00")
MAX_KELLY_BUDGET = Decimal("3.00")


@dataclass(frozen=True)
class Opportunity:
    ticker: str
    created_ns: int
    settled_ns: int
    settled_day: str
    block: int
    result: str
    seconds_left: int
    yes_bid: Decimal
    yes_ask: Decimal
    market_yes_probability: float
    raw_yes_probability: float

    @property
    def no_ask(self):
        return Decimal(1) - self.yes_bid

    @property
    def spread(self):
        return self.yes_ask - self.yes_bid


def _logit(probability: float) -> float:
    value = min(0.999999, max(0.000001, probability))
    return math.log(value / (1 - value))


def blend_probability(raw_probability: float, market_probability: float, market_weight: float) -> float:
    log_odds = (1 - market_weight) * _logit(raw_probability) + market_weight * _logit(
        market_probability
    )
    return 1 / (1 + math.exp(-log_odds))


def full_kelly_fraction(probability: float, unit_cost: Decimal) -> Decimal:
    if not 0 < unit_cost < 1:
        return Decimal(0)
    value = (Decimal(str(probability)) - unit_cost) / (1 - unit_cost)
    return max(Decimal(0), value)


def _quantity(price: Decimal, budget: Decimal, cash: Decimal, cfg: Experiment) -> int:
    budget = min(budget, cash)
    if budget <= 0 or not 0 < price < 1:
        return 0
    count = int(budget / price)
    while count and price * count + entry_fee(price, count, cfg) > budget:
        count -= 1
    return count


def _budget(variant: str, probability: float, price: Decimal, cash: Decimal, cfg: Experiment):
    settings = SIZING_VARIANTS[variant]
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


def build_tape(database: Path, audit_path: Path):
    partitions, candles, benchmark, exclusions = load_source(database, audit_path)
    markets = sorted(
        partitions["development"] + partitions["validation"],
        key=lambda row: (row.close_second, row.ticker),
    )
    eligible = []
    excluded = Counter()
    for market in markets:
        reasons = [name for name, tickers in exclusions.items() if market.ticker in tickers]
        if market.ticker not in candles:
            reasons.append("missing_candle_history")
        if reasons:
            for reason in set(reasons):
                excluded[reason] += 1
            continue
        eligible.append(market)
    tape = []
    for index, market in enumerate(eligible):
        block = min(4, index * 5 // len(eligible))
        rows = []
        for quote in candles[market.ticker]:
            seconds_left = market.close_second - quote.second
            if not 5 <= seconds_left <= 300:
                continue
            fair = forecast(market, quote.second, benchmark, adaptive=True)
            if fair is None:
                continue
            rows.append(
                Opportunity(
                    ticker=market.ticker,
                    created_ns=quote.second * NANOSECONDS,
                    settled_ns=market.close_second * NANOSECONDS,
                    settled_day=datetime.fromtimestamp(
                        market.close_second, timezone.utc
                    ).date().isoformat(),
                    block=block,
                    result=market.result,
                    seconds_left=seconds_left,
                    yes_bid=quote.yes_bid,
                    yes_ask=quote.yes_ask,
                    market_yes_probability=quote.midpoint,
                    raw_yes_probability=fair["yes_probability"],
                )
            )
        tape.append((market, rows))
    return {
        "tape": tape,
        "benchmark": benchmark,
        "eligible_markets": len(eligible),
        "excluded_unique_markets": len(markets) - len(eligible),
        "exclusion_memberships": dict(sorted(excluded.items())),
        "observed_dates": sorted({row[0].close_second // 86400 for row in tape}),
        "holdout_markets": len(partitions["holdout"]),
        "original_validation_start_ns": min(
            row.close_second for row in partitions["validation"]
        )
        * NANOSECONDS,
    }


def select_decisions(tape, parameters: dict, cfg: Experiment):
    decisions = []
    rejections = Counter()
    weight = parameters["probability_market_log_odds_weight"]
    for _market, opportunities in tape:
        chosen = None
        for row in opportunities:
            if row.seconds_left > parameters["maximum_seconds_left"]:
                continue
            blended_yes = blend_probability(
                row.raw_yes_probability,
                row.market_yes_probability,
                weight,
            )
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
                abs(row.raw_yes_probability - row.market_yes_probability)
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
                "block": row.block,
                "result": row.result,
                "side": side,
                "price": price,
                "probability": probability,
                "raw_yes_probability": row.raw_yes_probability,
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
    kelly_cap_binding_decisions = 0
    target_budgets = []
    trades = []
    for decision in decisions:
        budget, kelly = _budget(
            variant,
            decision["probability"],
            decision["price"],
            cash,
            cfg,
        )
        quantity = _quantity(decision["price"], budget, cash, cfg)
        target_budgets.append(budget)
        if kelly is not None and budget == MAX_KELLY_BUDGET:
            kelly_cap_binding_decisions += 1
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
                "cash_after": cash,
                "full_kelly_fraction": kelly,
                "target_budget": budget,
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
    for trade in trades:
        daily[trade["settled_day"]] += trade["pnl"]
        blocks[trade["block"]] += trade["pnl"]
    positive_day_share = (
        sum(value > 0 for value in daily.values()) / len(daily) if daily else None
    )
    daily_values = [float(value) for value in daily.values()]
    daily_mean = sum(daily_values) / len(daily_values) if daily_values else None
    if len(daily_values) > 1:
        daily_variance = sum((value - daily_mean) ** 2 for value in daily_values) / (
            len(daily_values) - 1
        )
        daily_standard_error = math.sqrt(daily_variance / len(daily_values))
        daily_mean_interval = [
            daily_mean - 1.96 * daily_standard_error,
            daily_mean + 1.96 * daily_standard_error,
        ]
    else:
        daily_standard_error = None
        daily_mean_interval = None
    side_counts = Counter(row["side"] for row in trades)
    seconds_left_counts = Counter(row["seconds_left"] for row in trades)
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
        "positive_day_share": positive_day_share,
        "positive_days": sum(value > 0 for value in daily.values()),
        "observed_days": len(observed_days),
        "mean_daily_pnl": daily_mean,
        "daily_pnl_standard_error": daily_standard_error,
        "mean_daily_pnl_95pct_normal_interval": daily_mean_interval,
        "block_pnl": [str(value) for value in blocks],
        "positive_blocks": sum(value > 0 for value in blocks),
        "minimum_block_pnl": str(min(blocks)),
        "zero_size_decisions": dict(sorted(zero_size.items())),
        "kelly_cap_binding_decisions": (
            kelly_cap_binding_decisions if SIZING_VARIANTS[variant]["kind"] == "fractional_kelly" else None
        ),
        "mean_target_budget": (
            str(sum(target_budgets, Decimal(0)) / len(target_budgets)) if target_budgets else None
        ),
        "entry_diagnostics": {
            "side_counts": dict(sorted(side_counts.items())),
            "seconds_left_counts": {
                str(key): value for key, value in sorted(seconds_left_counts.items())
            },
            "minimum_entry_price": str(min(entry_prices)) if entry_prices else None,
            "mean_entry_price": (
                str(sum(entry_prices, Decimal(0)) / len(entry_prices)) if entry_prices else None
            ),
            "maximum_entry_price": str(max(entry_prices)) if entry_prices else None,
        },
        "inability_to_afford_any_later_trade": cash <= 0,
        "largest_winner_pnl": str(winners[0]) if winners else None,
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


def _gates(summary: dict):
    return {
        "minimum_100_settlements": summary["settled_markets"] >= 100,
        "positive_net_pnl": Decimal(summary["realized_net_pnl"]) > 0,
        "positive_without_top_three_winners": Decimal(
            summary["pnl_without_top_three_winners"]
        )
        > 0,
        "positive_one_cent_stress": Decimal(summary["stressed_pnl"]["1"]) > 0,
        "positive_two_cent_stress": Decimal(summary["stressed_pnl"]["2"]) > 0,
        "positive_on_majority_of_days": summary["positive_day_share"] is not None
        and summary["positive_day_share"] > 0.5,
        "positive_in_four_of_five_blocks": summary["positive_blocks"] >= 4,
        "maximum_drawdown_at_most_10": Decimal(summary["maximum_drawdown"]) <= 10,
    }


def _ranking_key(row):
    fixed = row["sizing"]["fixed_1"]
    return (
        row["review_gate_passed"],
        Decimal(fixed["minimum_block_pnl"]),
        Decimal(fixed["pnl_without_top_three_winners"]),
        Decimal(fixed["stressed_pnl"]["2"]),
        -Decimal(fixed["maximum_drawdown"]),
        fixed["settled_markets"],
    )


def run_study(database: Path, audit_path: Path):
    source = build_tape(database, audit_path)
    observed_days = sorted(
        {
            datetime.fromtimestamp(day * 86400, timezone.utc).date().isoformat()
            for day in source["observed_dates"]
        }
    )
    cfg = Experiment()
    results = []
    for parameters in configurations():
        decisions, rejections = select_decisions(source["tape"], parameters, cfg)
        sizing = {
            variant: run_sizing(decisions, variant, observed_days, cfg)
            for variant in SIZING_VARIANTS
        }
        gates = _gates(sizing["fixed_1"])
        results.append(
            {
                "configuration": parameters,
                "decision_rejections": dict(sorted(rejections.items())),
                "sizing": sizing,
                "gates": gates,
                "review_gate_passed": all(gates.values()),
            }
        )
    ranked = sorted(results, key=lambda row: row["configuration"]["name"])
    ranked.sort(key=_ranking_key, reverse=True)
    eligible = [row for row in ranked if row["review_gate_passed"]]
    baseline_name = "w00_e040_p3085_g060_t300_s01_b00"
    baseline = next(row for row in results if row["configuration"]["name"] == baseline_name)
    selected_split_diagnostic = None
    if eligible:
        selected_decisions, _ = select_decisions(source["tape"], eligible[0]["configuration"], cfg)
        cutoff = source["original_validation_start_ns"]
        development_decisions = [row for row in selected_decisions if row["settled_ns"] < cutoff]
        validation_decisions = [row for row in selected_decisions if row["settled_ns"] >= cutoff]
        development_days = sorted(
            {
                datetime.fromtimestamp(market.close_second, timezone.utc).date().isoformat()
                for market, _rows in source["tape"]
                if market.close_second * NANOSECONDS < cutoff
            }
        )
        validation_days = sorted(
            {
                datetime.fromtimestamp(market.close_second, timezone.utc).date().isoformat()
                for market, _rows in source["tape"]
                if market.close_second * NANOSECONDS >= cutoff
            }
        )
        selected_split_diagnostic = {
            "post_selection_diagnostic_not_an_additional_gate": True,
            "original_development": run_sizing(
                development_decisions, "fixed_1", development_days, cfg
            ),
            "original_validation": run_sizing(
                validation_decisions, "fixed_1", validation_days, cfg
            ),
        }
    report = {
        "study": "019",
        "state": "complete" if eligible else "complete_no_signal_winner",
        "registration": registration(),
        "registration_sha256": registration_hash(),
        "source": {
            "eligible_research_markets": source["eligible_markets"],
            "excluded_unique_markets": source["excluded_unique_markets"],
            "exclusion_memberships": source["exclusion_memberships"],
            "observed_utc_dates": len(observed_days),
            "holdout_markets": source["holdout_markets"],
            "holdout_evaluated": False,
            "benchmark_top_of_second_values_loaded": source["benchmark"].loaded_seconds,
        },
        "configurations_evaluated": len(results),
        "signal_gate_passers": len(eligible),
        "selected_signal": eligible[0]["configuration"] if eligible else None,
        "selected_signal_original_partition_diagnostic": selected_split_diagnostic,
        "baseline": baseline,
        "top_diagnostic_configurations": ranked[:20],
        "all_configurations": sorted(results, key=lambda row: row["configuration"]["name"]),
        "holdout": {
            "locked": True,
            "evaluated": False,
            "reason": "no fixed_1 gate-passing signal" if not eligible else "awaiting explicit authorization",
        },
        "production_orders_authorized": False,
    }
    report["report_sha256"] = hashlib.sha256(canonical(report)).hexdigest()
    return report
