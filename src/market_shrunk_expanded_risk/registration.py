from __future__ import annotations

import hashlib

from historical_backtest.registration import (
    SOURCE_AUDIT_SHA256,
    SOURCE_CHAIN_SHA256,
    SOURCE_DATABASE_SHA256,
)
from historical_market_confirmation.kelly_registration import SIGNAL
from research_lab.storage import canonical

STUDY = "027"
EXPECTED_FIXED_LEDGER = "149f874d7e98af5b4720b0b1ee7a489d8e05b7330db93bf45f74e7c9fae37773"
RISK_GRID = {
    f"{fraction}_kelly_cap_{cap}": {
        "multiplier": multiplier,
        "cap_dollars": f"{cap}.00",
    }
    for fraction, multiplier in (("quarter", "0.25"), ("half", "0.50"))
    for cap in (3, 4, 5, 6)
}


def registration():
    return {
        "study": STUDY,
        "name": "market_shrunk_expanded_kelly_cap_study_027",
        "declared_date": "2026-10-22",
        "objective": (
            "Measure how quarter- and half-Kelly exposure changes when the all-in per-market cap rises from "
            "$3 to $4, $5 or $6 on Study 023's exact decisions."
        ),
        "source": {
            "series": "KXBTC15M",
            "database_sha256": SOURCE_DATABASE_SHA256,
            "audit_sha256": SOURCE_AUDIT_SHA256,
            "event_chain_sha256": SOURCE_CHAIN_SHA256,
            "research_partition": "already-viewed oldest 80% used by Studies 023 and 024",
            "holdout": "newest 20% remains locked and unevaluated",
            "expected_fixed_1_trade_ledger_sha256": EXPECTED_FIXED_LEDGER,
        },
        "signal": SIGNAL,
        "risk": {
            "starting_bankroll_dollars": "100.00",
            "grid": RISK_GRID,
            "kelly_probability": "the frozen market-shrunk modeled probability",
            "kelly_unit_cost": "entry price plus one-contract Kalshi entry fee",
            "integer_contracts": True,
            "fees_inside_budget": True,
            "stress_rule": "keep base quantity and add one or two cents to every contract entry",
            "no_daily_stop_or_cooldown": True,
            "hold_to_official_settlement": True,
        },
        "reporting": {
            "metrics": [
                "trades, wins, contracts and fees",
                "ending bankroll and net P&L",
                "P&L without the three largest winners",
                "one- and two-cent adverse-price P&L",
                "maximum drawdown and longest loss streak",
                "positive-day share and five chronological blocks",
                "cap-binding decisions and mean target budget",
                "two-cent-stress-to-drawdown ratio",
            ],
            "comparisons": [
                "incremental P&L and drawdown relative to the same Kelly fraction at $3",
                "highest base P&L",
                "highest two-cent-stressed P&L",
                "best two-cent-stress-to-drawdown ratio",
            ],
        },
        "interpretation": {
            "risk_only": True,
            "cannot_establish_or_improve_signal_edge": True,
            "study_023_failed_original_gates": True,
            "holdout_evaluated": False,
            "production_change_authorized": False,
            "production_orders_authorized": False,
            "warning": (
                "Higher caps magnify both profit and model error. Favorable historical P&L cannot authorize a "
                "live cap increase."
            ),
        },
    }


def registration_hash():
    return hashlib.sha256(canonical(registration())).hexdigest()
