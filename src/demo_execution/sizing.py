"""Signal-only risk sizing comparisons for production quote audits."""
from __future__ import annotations

from decimal import Decimal

from candidate_study.engine import calibrated_probability
from research_lab.engine import entry_fee

REFERENCE_BANKROLL = Decimal("100.00")
MAX_RISK_PER_MARKET = Decimal("3.00")
SIZING_REVISION = "production-arrival-sizing-001"
KELLY_MULTIPLIERS = {
    "eighth_kelly_cap_3": Decimal("0.125"),
    "quarter_kelly_cap_3": Decimal("0.25"),
    "half_kelly_cap_3": Decimal("0.5"),
}


def _quantity(price, budget, cfg):
    count = int(budget / price)
    while count and price * count + entry_fee(price, count, cfg) > budget:
        count -= 1
    return count


def sizing_plan(side, raw_yes_probability, price, depth, cfg):
    """Size one observed production quote without placing an order."""
    price, depth = Decimal(price), Decimal(depth)
    calibrated_yes = calibrated_probability(float(raw_yes_probability))
    probability = calibrated_yes if side == "yes" else 1 - calibrated_yes
    unit_cost = price + entry_fee(price, 1, cfg)
    full_kelly = max(Decimal(0), (Decimal(str(probability)) - unit_cost) / (1 - unit_cost))
    budgets = {
        "fixed_1": Decimal("1.00"),
        "fixed_3": MAX_RISK_PER_MARKET,
        **{name: min(MAX_RISK_PER_MARKET, REFERENCE_BANKROLL * full_kelly * multiplier)
           for name, multiplier in KELLY_MULTIPLIERS.items()},
    }
    variants = {}
    for name, budget in budgets.items():
        count = _quantity(price, budget, cfg)
        cost = price * count + entry_fee(price, count, cfg) if count else Decimal(0)
        variants[name] = {
            "target_budget": str(budget),
            "contracts": count,
            "modeled_cost": str(cost),
            "depth_sufficient": depth >= count,
        }
    return {
        "revision": SIZING_REVISION,
        "execution": "shadow_only_no_order",
        "reference_bankroll": str(REFERENCE_BANKROLL),
        "maximum_risk_per_market": str(MAX_RISK_PER_MARKET),
        "probability_source": "frozen_candidate_003_temperature_calibration",
        "raw_yes_probability": raw_yes_probability,
        "selected_probability": probability,
        "all_in_unit_cost": str(unit_cost),
        "full_kelly_fraction": str(full_kelly),
        "variants": variants,
    }


def summarize_sizing(rows):
    """Summarize settled, depth-supported shadow plans in signal order."""
    names = ("fixed_1", "fixed_3", *KELLY_MULTIPLIERS)
    summaries = {name: {"signals": 0, "not_production_qualified": 0,
                        "evaluated": 0, "zero_size": 0,
                        "insufficient_depth": 0, "wins": 0, "net_pnl": Decimal(0),
                        "maximum_drawdown": Decimal(0), "equity": REFERENCE_BANKROLL,
                        "peak_equity": REFERENCE_BANKROLL}
                 for name in names}
    for row in rows:
        plan, result = row.get("risk_sizing"), row.get("market_result")
        if not plan or plan.get("revision") != SIZING_REVISION or result not in ("yes", "no"):
            continue
        won = result == row.get("side")
        for name in names:
            summary = summaries[name]
            summary["signals"] += 1
            if not row.get("production_qualified"):
                summary["not_production_qualified"] += 1
                continue
            variant = plan["variants"][name]
            count = int(variant["contracts"])
            if count < 1:
                summary["zero_size"] += 1
                continue
            if not variant["depth_sufficient"]:
                summary["insufficient_depth"] += 1
                continue
            pnl = Decimal(count if won else 0) - Decimal(variant["modeled_cost"])
            summary["evaluated"] += 1
            summary["wins"] += int(won)
            summary["net_pnl"] += pnl
            summary["equity"] += pnl
            summary["peak_equity"] = max(summary["peak_equity"], summary["equity"])
            summary["maximum_drawdown"] = max(
                summary["maximum_drawdown"], summary["peak_equity"] - summary["equity"])
    for summary in summaries.values():
        summary["win_rate"] = (summary["wins"] / summary["evaluated"]
                               if summary["evaluated"] else None)
        for key in ("net_pnl", "maximum_drawdown", "equity"):
            summary[key] = str(summary[key])
        summary.pop("peak_equity")
    return {
        "revision": SIZING_REVISION,
        "execution": "production_quote_shadow; 500ms arrival snapshot; no order",
        "reference_bankroll": str(REFERENCE_BANKROLL),
        "maximum_risk_per_market": str(MAX_RISK_PER_MARKET),
        "probability_source": "frozen_candidate_003_temperature_calibration",
        "results": summaries,
    }
