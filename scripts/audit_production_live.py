"""Aggregate sanitized production-ledger evidence into a live-trade audit."""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from decimal import Decimal
from pathlib import Path


def decimal(value):
    return Decimal(str(value))


def band(value, cuts, labels):
    for cut, label in zip(cuts, labels, strict=False):
        if value < cut:
            return label
    return labels[-1]


def summary(rows):
    actual = [decimal(row["actual_pnl"]) for row in rows]
    hold = [decimal(row["hold_pnl"]) for row in rows]
    probabilities = [decimal(row["model_probability"]) for row in rows]
    outcomes = [Decimal(row["official_result"] == row["side"]) for row in rows]
    expected_hold = [
        probability * decimal(row["filled_contracts"]) - decimal(row["entry_cost"])
        for probability, row in zip(probabilities, rows, strict=True)
    ]
    equity = peak = Decimal("100")
    maximum_drawdown = Decimal(0)
    for pnl in actual:
        equity += pnl
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, peak - equity)
    winners = sorted((pnl for pnl in actual if pnl > 0), reverse=True)
    top_three = sum(winners[:3], Decimal(0))
    positive = sum(winners, Decimal(0))
    brier = (
        sum(((probability - outcome) ** 2 for probability, outcome in zip(
            probabilities, outcomes, strict=True
        )), Decimal(0)) / len(rows)
        if rows else None
    )
    log_loss = (
        -sum(
            math.log(max(1e-12, float(probability if outcome else 1 - probability)))
            for probability, outcome in zip(probabilities, outcomes, strict=True)
        ) / len(rows)
        if rows else None
    )
    return {
        "trades": len(rows),
        "wins": int(sum(outcomes, Decimal(0))),
        "losses": len(rows) - int(sum(outcomes, Decimal(0))),
        "win_rate": float(sum(outcomes, Decimal(0)) / len(rows)) if rows else None,
        "mean_modeled_probability": (
            float(sum(probabilities, Decimal(0)) / len(rows)) if rows else None
        ),
        "expected_wins": float(sum(probabilities, Decimal(0))),
        "actual_net_pnl": str(sum(actual, Decimal(0))),
        "hold_to_settlement_net_pnl": str(sum(hold, Decimal(0))),
        "exit_advantage": str(sum(actual, Decimal(0)) - sum(hold, Decimal(0))),
        "model_expected_hold_pnl": str(sum(expected_hold, Decimal(0))),
        "model_expectation_gap": str(
            sum(hold, Decimal(0)) - sum(expected_hold, Decimal(0))
        ),
        "entry_cost": str(sum((decimal(row["entry_cost"]) for row in rows), Decimal(0))),
        "entry_fees": str(sum((decimal(row["entry_fees"]) for row in rows), Decimal(0))),
        "maximum_drawdown": str(maximum_drawdown),
        "top_three_winner_pnl": str(top_three),
        "pnl_without_top_three_winners": str(sum(actual, Decimal(0)) - top_three),
        "top_three_share_of_positive_pnl": float(top_three / positive) if positive else None,
        "brier_score": float(brier) if brier is not None else None,
        "log_loss": log_loss,
        "calibration_gap_observed_minus_modeled": (
            float(sum(outcomes, Decimal(0)) / len(rows) - sum(probabilities, Decimal(0)) / len(rows))
            if rows else None
        ),
    }


def grouped(rows, key):
    groups = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    return {name: summary(group) for name, group in sorted(groups.items())}


def independence_diagnostic(rows):
    win_distribution = {0: 1.0}
    payout_distribution = {0: 1.0}
    for row in rows:
        probability = float(row["model_probability"])
        contracts = decimal(row["filled_contracts"])
        if contracts != int(contracts):
            raise ValueError("Independence payout diagnostic requires integer entry fills")
        contracts = int(contracts)
        win_distribution = {
            wins: (
                win_distribution.get(wins, 0) * (1 - probability)
                + win_distribution.get(wins - 1, 0) * probability
            )
            for wins in range(max(win_distribution) + 2)
        }
        payout_distribution = {
            payout: (
                payout_distribution.get(payout, 0) * (1 - probability)
                + payout_distribution.get(payout - contracts, 0) * probability
            )
            for payout in range(max(payout_distribution) + contracts + 1)
        }
    actual_wins = sum(row["official_result"] == row["side"] for row in rows)
    actual_hold_payout = sum(
        (decimal(row["hold_pnl"]) + decimal(row["entry_cost"]) for row in rows),
        Decimal(0),
    )
    return {
        "assumption": "Independent Bernoulli outcomes at each recorded model probability.",
        "actual_wins": actual_wins,
        "probability_of_actual_wins_or_fewer": sum(
            probability for wins, probability in win_distribution.items() if wins <= actual_wins
        ),
        "actual_hold_payout": str(actual_hold_payout),
        "probability_of_actual_hold_payout_or_lower": sum(
            probability
            for payout, probability in payout_distribution.items()
            if Decimal(payout) <= actual_hold_payout
        ),
        "warning": "Adjacent 15-minute markets are correlated, so these are diagnostics rather than valid final p-values.",
    }


def audit(payload):
    rows = payload["trades"]
    if not rows or any(row["actual_pnl"] is None or row["hold_pnl"] is None for row in rows):
        raise ValueError("Every filled production trade must have an official resolved result")
    return {
        "study": "production-live-audit-001",
        "scope": "All 37 officially resolved real-money adaptive-volatility fills through the entry pause on 2026-10-08.",
        "overall": summary(rows),
        "independence_diagnostic": independence_diagnostic(rows),
        "by_phase": grouped(rows, lambda row: row["phase"]),
        "by_side": grouped(rows, lambda row: row["side"]),
        "by_entry_price": grouped(
            rows,
            lambda row: band(
                decimal(row["entry_price"]),
                [Decimal("0.10"), Decimal("0.20"), Decimal("0.40")],
                ["below_10c", "10_to_19c", "20_to_39c", "40c_and_above"],
            ),
        ),
        "by_modeled_probability": grouped(
            rows,
            lambda row: band(
                decimal(row["model_probability"]),
                [Decimal("0.10"), Decimal("0.20"), Decimal("0.40"), Decimal("0.60"), Decimal("0.80")],
                ["below_10pct", "10_to_19pct", "20_to_39pct", "40_to_59pct", "60_to_79pct", "80pct_and_above"],
            ),
        ),
        "by_modeled_edge": grouped(
            rows,
            lambda row: band(
                decimal(row["modeled_edge"]),
                [Decimal("0.05"), Decimal("0.075")],
                ["4_to_4_99pct", "5_to_7_49pct", "7_5pct_and_above"],
            ),
        ),
        "by_seconds_left": grouped(
            rows,
            lambda row: band(
                decimal(row["seconds_left"]),
                [Decimal("60"), Decimal("180")],
                ["5_to_59", "60_to_179", "180_to_300"],
            ),
        ),
        "largest_losses": [
            {
                key: row[key]
                for key in (
                    "ticker", "phase", "side", "model_probability", "modeled_edge",
                    "entry_price", "filled_contracts", "entry_cost", "official_result",
                    "actual_pnl", "hold_pnl",
                )
            }
            for row in sorted(rows, key=lambda row: decimal(row["actual_pnl"]))[:5]
        ],
        "limitations": [
            "This is an in-sample diagnostic of the complete live record, not a new strategy backtest.",
            "The phases were changed after observing results and cannot be compared as randomized experiments.",
            "Adjacent 15-minute outcomes and model errors are not independent.",
            "Small price and probability groups have wide uncertainty; no filter is promoted from this audit alone.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(json.loads(args.input.read_text()))
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
