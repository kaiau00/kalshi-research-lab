from __future__ import annotations

import hashlib
import math
from collections import Counter
from decimal import Decimal
from pathlib import Path

from historical_frequency_optimization.study import build_tape
from historical_optimization.study import full_kelly_fraction
from research_lab.engine import entry_fee
from research_lab.settings import Experiment
from research_lab.storage import canonical

from .kelly_registration import RISK_VARIANTS, SIGNAL, registration, registration_hash
from .study import _normalize, select_decisions

STARTING_CASH = Decimal("100.00")
KELLY_CAP = Decimal("3.00")
EXPECTED_FIXED_LEDGER = "149f874d7e98af5b4720b0b1ee7a489d8e05b7330db93bf45f74e7c9fae37773"


def quantity_for_budget(price: Decimal, budget: Decimal, cash: Decimal, cfg: Experiment) -> int:
    budget = min(budget, cash)
    if budget <= 0 or not 0 < price < 1:
        return 0
    quantity = int(budget / price)
    while quantity and price * quantity + entry_fee(price, quantity, cfg) > budget:
        quantity -= 1
    return quantity


def target_budget(
    variant: str,
    probability: float,
    price: Decimal,
    cash: Decimal,
    cfg: Experiment,
    *,
    kelly_cap: Decimal | None = None,
    kelly_multiplier: Decimal | None = None,
):
    settings = RISK_VARIANTS[variant]
    if settings["kind"] == "fixed":
        return min(Decimal(settings["maximum_all_in_dollars"]), cash), None
    unit_cost = price + entry_fee(price, 1, cfg)
    full_kelly = full_kelly_fraction(probability, unit_cost)
    cap = kelly_cap if kelly_cap is not None else Decimal(settings.get("cap", KELLY_CAP))
    multiplier = (
        kelly_multiplier
        if kelly_multiplier is not None
        else Decimal(settings["multiplier"])
    )
    budget = min(
        cap,
        cash * full_kelly * multiplier,
        cash,
    )
    return budget, full_kelly


def _stress_pnl(trade: dict, cents: int, cfg: Experiment):
    price = min(Decimal("0.999999"), trade["price"] + Decimal(cents) / 100)
    return trade["payout"] - price * trade["quantity"] - entry_fee(
        price, trade["quantity"], cfg
    )


def run_variant(
    decisions: list[dict],
    variant: str,
    observed_days: list[str],
    cfg: Experiment,
    *,
    kelly_cap: Decimal | None = None,
    kelly_multiplier: Decimal | None = None,
    result_name: str | None = None,
):
    cash = STARTING_CASH
    peak = STARTING_CASH
    maximum_drawdown = Decimal(0)
    target_budgets = []
    zero_size = Counter()
    cap_binding = 0
    trades = []
    longest_loss_streak = 0
    current_loss_streak = 0
    for decision in decisions:
        budget, full_kelly = target_budget(
            variant,
            decision["probability"],
            decision["price"],
            cash,
            cfg,
            kelly_cap=kelly_cap,
            kelly_multiplier=kelly_multiplier,
        )
        target_budgets.append(budget)
        effective_cap = (
            kelly_cap
            if kelly_cap is not None
            else Decimal(RISK_VARIANTS[variant].get("cap", KELLY_CAP))
        )
        if full_kelly is not None and budget == effective_cap:
            cap_binding += 1
        quantity = quantity_for_budget(decision["price"], budget, cash, cfg)
        if quantity < 1:
            zero_size["kelly_budget_below_one_contract"] += 1
            continue
        fee = entry_fee(decision["price"], quantity, cfg)
        cost = decision["price"] * quantity + fee
        won = decision["side"] == decision["result"]
        payout = Decimal(quantity if won else 0)
        pnl = payout - cost
        cash += pnl
        peak = max(peak, cash)
        maximum_drawdown = max(maximum_drawdown, peak - cash)
        if pnl < 0:
            current_loss_streak += 1
            longest_loss_streak = max(longest_loss_streak, current_loss_streak)
        else:
            current_loss_streak = 0
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
                "full_kelly_fraction": full_kelly,
            }
        )

    pnls = [row["pnl"] for row in trades]
    net_pnl = sum(pnls, Decimal(0))
    winners = sorted((value for value in pnls if value > 0), reverse=True)
    positive_pnl = sum(winners, Decimal(0))
    top_three = sum(winners[:3], Decimal(0))
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
    budgets_used = [row["target_budget"] for row in trades]
    result = {
        "variant": result_name or variant,
        "decisions": len(decisions),
        "trades": len(trades),
        "skipped_decisions": len(decisions) - len(trades),
        "contracts": sum(row["quantity"] for row in trades),
        "wins": sum(row["won"] for row in trades),
        "win_rate": sum(row["won"] for row in trades) / len(trades) if trades else None,
        "fees": str(sum((row["fee"] for row in trades), Decimal(0))),
        "net_pnl": str(net_pnl),
        "ending_bankroll": str(cash),
        "pnl_without_top_three_winners": str(net_pnl - top_three),
        "top_three_winner_pnl": str(top_three),
        "top_three_share_of_positive_pnl": (
            float(top_three / positive_pnl) if positive_pnl > 0 else None
        ),
        "stressed_pnl": {key: str(value) for key, value in stress.items()},
        "maximum_drawdown": str(maximum_drawdown),
        "longest_loss_streak": longest_loss_streak,
        "positive_day_share": (
            sum(value > 0 for value in daily.values()) / len(daily) if daily else None
        ),
        "positive_days": sum(value > 0 for value in daily.values()),
        "observed_days": len(observed_days),
        "daily_mean_pnl": daily_mean,
        "daily_pnl_standard_error": standard_error,
        "daily_mean_one_sided_90pct_lower_bound": lower_90,
        "block_pnl": [str(value) for value in blocks],
        "positive_blocks": sum(value > 0 for value in blocks),
        "two_cent_stressed_block_pnl": [str(value) for value in stressed_blocks["2"]],
        "positive_two_cent_stressed_blocks": sum(value > 0 for value in stressed_blocks["2"]),
        "zero_size_decisions": dict(sorted(zero_size.items())),
        "kelly_cap_binding_decisions": cap_binding if variant != "fixed_1" else None,
        "mean_target_budget": (
            str(sum(budgets_used, Decimal(0)) / len(budgets_used)) if budgets_used else None
        ),
        "maximum_target_budget": str(max(budgets_used)) if budgets_used else None,
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
    drawdown = Decimal(result["maximum_drawdown"])
    stressed = Decimal(result["stressed_pnl"]["2"])
    result["risk_screen"] = {
        "positive_two_cent_stress": stressed > 0,
        "positive_without_top_three_winners": Decimal(
            result["pnl_without_top_three_winners"]
        )
        > 0,
        "maximum_drawdown_at_most_10": drawdown <= 10,
    }
    result["two_cent_stress_to_drawdown"] = (
        str(stressed / drawdown) if drawdown > 0 else None
    )
    return result


def run_study(database: Path, audit_path: Path):
    source = build_tape(database, audit_path)
    cfg = Experiment()
    decisions, rejections = select_decisions(source["tape"], SIGNAL, cfg)
    decisions = _normalize(decisions)
    sizing = {
        variant: run_variant(decisions, variant, source["observed_days"], cfg)
        for variant in RISK_VARIANTS
    }
    if sizing["fixed_1"]["trade_ledger_sha256"] != EXPECTED_FIXED_LEDGER:
        raise ValueError("Study 024 fixed-$1 replay does not reproduce Study 023")
    eligible = []
    for name, summary in sizing.items():
        if all(summary["risk_screen"].values()):
            eligible.append(
                (
                    Decimal(summary["two_cent_stress_to_drawdown"]),
                    -Decimal(summary["mean_target_budget"]),
                    name,
                )
            )
    eligible.sort(reverse=True)
    descriptive_leader = eligible[0][-1] if eligible else None
    report = {
        "study": "024",
        "state": "complete",
        "registration": registration(),
        "registration_sha256": registration_hash(),
        "source": {
            "observed_utc_dates": len(source["observed_days"]),
            "eligible_research_markets": source["eligible_markets"],
            "holdout_markets": source["holdout_markets"],
            "holdout_evaluated": False,
        },
        "signal": SIGNAL,
        "decision_rejections": dict(sorted(rejections.items())),
        "fixed_signal_decisions": len(decisions),
        "sizing": sizing,
        "descriptive_risk_adjusted_leader": descriptive_leader,
        "promotion_or_execution_authorized": False,
        "holdout": {"locked": True, "evaluated": False},
    }
    report["report_sha256"] = hashlib.sha256(canonical(report)).hexdigest()
    return report


def public_summary(report: dict):
    return {key: value for key, value in report.items() if key not in {"registration", "decision_rejections"}}
