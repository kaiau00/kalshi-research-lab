from __future__ import annotations

import hashlib

from historical_backtest.registration import (
    SOURCE_AUDIT_SHA256,
    SOURCE_CHAIN_SHA256,
    SOURCE_DATABASE_SHA256,
)
from research_lab.storage import canonical

STUDY = "024"
SIGNAL = {
    "name": "v90_w25_q0_e005_p4580_g075_t005300_s02_b00_rnone",
    "fast_variance_weight": 0.90,
    "probability_market_log_odds_weight": 0.25,
    "quote_confirmation": "none",
    "trend_multiplier": 0.0,
    "minimum_net_edge": 0.005,
    "minimum_selected_ask": 0.45,
    "maximum_selected_ask_exclusive": 0.80,
    "maximum_raw_model_market_gap": 0.075,
    "minimum_seconds_left": 5,
    "maximum_seconds_left": 300,
    "maximum_binary_spread": 0.02,
    "minimum_two_cent_stressed_edge": 0.0,
    "maximum_fast_slow_variance_ratio": None,
}
RISK_VARIANTS = {
    "fixed_1": {"kind": "fixed", "maximum_all_in_dollars": "1.00"},
    "kelly_1_32_cap_3": {"kind": "kelly", "multiplier": "0.03125", "cap": "3.00"},
    "kelly_1_16_cap_3": {"kind": "kelly", "multiplier": "0.0625", "cap": "3.00"},
    "kelly_1_8_cap_3": {"kind": "kelly", "multiplier": "0.125", "cap": "3.00"},
    "kelly_1_4_cap_3": {"kind": "kelly", "multiplier": "0.25", "cap": "3.00"},
    "kelly_1_2_cap_3": {"kind": "kelly", "multiplier": "0.50", "cap": "3.00"},
}


def registration():
    return {
        "study": STUDY,
        "name": "market_shrunk_kelly_risk_study_024",
        "declared_date": "2026-10-19",
        "selection_source": {
            "study": "023",
            "signal": SIGNAL["name"],
            "combined_fixed_1_trade_ledger_sha256": (
                "149f874d7e98af5b4720b0b1ee7a489d8e05b7330db93bf45f74e7c9fae37773"
            ),
            "warning": "Study 023 failed its frozen validation gate; sizing cannot promote the signal",
        },
        "source": {
            "series": "KXBTC15M",
            "database_sha256": SOURCE_DATABASE_SHA256,
            "audit_sha256": SOURCE_AUDIT_SHA256,
            "event_chain_sha256": SOURCE_CHAIN_SHA256,
            "research_partition": "the already-viewed oldest 80% from Dataset 017",
            "holdout": "newest 20% remains locked and unevaluated",
        },
        "signal": SIGNAL,
        "risk": {
            "starting_bankroll_dollars": "100.00",
            "variants": RISK_VARIANTS,
            "kelly_probability": "the signal's frozen market-shrunk modeled probability",
            "kelly_unit_cost": "entry price plus one-contract Kalshi entry fee",
            "integer_contracts": True,
            "fees_inside_budget": True,
            "maximum_kelly_all_in_dollars_per_market": "3.00",
            "zero_size_rule": "skip when the Kelly budget cannot buy one contract including fee",
            "stress_rule": "keep each base quantity and add one or two cents to every contract entry",
            "no_daily_stop_or_cooldown": True,
        },
        "reporting": {
            "metrics": [
                "trades and skipped decisions",
                "contracts and fees",
                "ending bankroll and net P&L",
                "P&L without three largest winners",
                "one- and two-cent adverse-price P&L",
                "maximum drawdown",
                "positive-day share and five chronological blocks",
                "top-three-winner concentration",
                "mean and maximum all-in target budget",
            ],
            "descriptive_ranking": [
                "positive two-cent stress and ex-top-three P&L",
                "maximum drawdown at most $10",
                "higher two-cent-stressed-P&L to drawdown ratio",
                "lower mean target budget",
            ],
        },
        "interpretation": {
            "risk_only": True,
            "cannot_rescue_or_promote_failed_signal": True,
            "holdout_evaluated": False,
            "production_orders_authorized": False,
            "kelly_model_risk_warning": (
                "Kelly assumes calibrated probabilities; the signal's historical regime instability can make "
                "all Kelly fractions overbet despite a favorable backtest."
            ),
        },
    }


def registration_hash():
    return hashlib.sha256(canonical(registration())).hexdigest()
