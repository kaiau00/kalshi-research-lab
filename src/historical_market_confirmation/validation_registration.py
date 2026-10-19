from __future__ import annotations

import hashlib

from historical_backtest.registration import (
    SOURCE_AUDIT_SHA256,
    SOURCE_CHAIN_SHA256,
    SOURCE_DATABASE_SHA256,
)
from historical_robust_optimization.registration import RISK_VARIANTS
from research_lab.storage import canonical

STUDY = "023"
CONFIGURATION = {
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


def registration():
    return {
        "study": STUDY,
        "name": "market_shrunk_fallback_validation_023",
        "declared_date": "2026-10-18",
        "selection_source": {
            "study": "022",
            "development_trade_ledger_sha256": (
                "7d86eba8d136a45129974695ca1f00a14173ed233e9ec1f6b881539a2ec34db1"
            ),
            "selection_reason": (
                "passed every Study 022 development gate except the requested 8-trade-per-day minimum"
            ),
        },
        "source": {
            "series": "KXBTC15M",
            "database_sha256": SOURCE_DATABASE_SHA256,
            "audit_sha256": SOURCE_AUDIT_SHA256,
            "event_chain_sha256": SOURCE_CHAIN_SHA256,
            "development": "oldest 60%; replay only to verify exact Study 022 selection",
            "validation": "next 20%; one frozen evaluation",
            "holdout": "newest 20% remains locked and unevaluated",
        },
        "configuration": CONFIGURATION,
        "validation_gate": {
            "average_trades_per_observed_day_between": [4.0, 7.0],
            "minimum_win_rate": 0.65,
            "mean_entry_price_between": ["0.45", "0.72"],
            "positive_base_ex_top_three_one_cent_and_two_cent_pnl": True,
            "positive_on_majority_of_days": True,
            "positive_in_three_of_five_base_blocks": True,
            "positive_two_cent_stress_in_three_of_five_blocks": True,
            "maximum_drawdown_at_most_dollars": "5.00",
        },
        "aggregate_gate": {
            "average_trades_per_observed_day_between": [4.0, 7.0],
            "minimum_base_pnl_exclusive": "24.4806",
            "minimum_pnl_without_top_three_exclusive": "21.2847",
            "minimum_two_cent_stressed_pnl_exclusive": "9.2233",
            "positive_in_four_of_five_base_blocks": True,
            "positive_two_cent_stress_in_four_of_five_blocks": True,
            "maximum_drawdown_at_most_dollars": "10.00",
            "positive_one_sided_90pct_daily_mean_lower_bound": True,
        },
        "risk": {
            "variants": RISK_VARIANTS,
            "opens_only_after_validation_and_aggregate_fixed_1_gates": True,
        },
        "interpretation": {
            "revised_lower_frequency_fallback": True,
            "does_not_satisfy_original_ten_trade_goal": True,
            "development_only": True,
            "holdout_evaluated": False,
            "production_orders_authorized": False,
        },
    }


def registration_hash():
    return hashlib.sha256(canonical(registration())).hexdigest()
