from __future__ import annotations

import hashlib

from research_lab.storage import canonical

STUDY = "018"
SOURCE_DATABASE_SHA256 = "31623b3a178d276bbc5fb0d8ab87600d90dfba7da98ead1099010ef0438a2d7f"
SOURCE_AUDIT_SHA256 = "dd361ab7ce8caed0c3861ce7953840d8034415046fcc78575a446c2bce755610"
SOURCE_CHAIN_SHA256 = "03526f0e63396de6cd8ddf8df77bcddbd83aff4d0753daf3f4b5285232b7c70f"

STRATEGIES = (
    "basic_fair_value",
    "tail_underdog",
    "adaptive_volatility",
    "market_agreement_band_001",
    "market_anchor_conservative_001",
    "moderate_disagreement_band_001",
)


def registration():
    return {
        "study": STUDY,
        "name": "historical_candle_strategy_screen_018",
        "declared_date": "2026-10-15",
        "source": {
            "series": "KXBTC15M",
            "interval": ["2026-04-15T00:00:00Z", "2026-10-15T00:00:00Z"],
            "database_sha256": SOURCE_DATABASE_SHA256,
            "audit_sha256": SOURCE_AUDIT_SHA256,
            "event_chain_sha256": SOURCE_CHAIN_SHA256,
            "settled_markets": 17_311,
        },
        "partition": {
            "method": "sort every source market by (close_time, ticker), then split 60/20/20 by count",
            "development": [0.0, 0.6],
            "validation": [0.6, 0.8],
            "holdout": [0.8, 1.0],
            "holdout_locked": True,
            "exclusions_are_applied_after_partitioning": True,
        },
        "data_quality_exclusions": {
            "source": "the fixed Dataset 017 audit",
            "categories": [
                "missing settlement-window BRTI ticks",
                "nonnumeric official expiration metadata",
                "missing or unsupported strike rule",
                "material BRTI reconstruction mismatch greater than one cent",
                "missing market candle history",
            ],
            "one_cent_settlement_differences_are_retained": True,
        },
        "decision_clock": {
            "opportunities": "one-minute Kalshi candle end timestamps with 5 through 300 seconds left",
            "quote": "YES bid/ask candle close known at the decision timestamp",
            "benchmark": "latest contiguous top-of-second BRTI at or before decision timestamp minus one second",
            "first_qualifying_decision_consumes_market": True,
            "arrival_fill_modeled": False,
        },
        "probability_models": {
            "basic": "600-second contiguous one-second mean squared log return variance",
            "adaptive": "70% 60-second plus 30% 600-second mean squared log return variance",
            "settlement": "conditional Gaussian distribution of the exact close-exclusive 60-second average",
            "continuity_correction_dollars": "0.005",
            "minimum_returns": 60,
        },
        "strategies": {
            "basic_fair_value": {"model": "basic", "minimum_net_edge": 0.04},
            "tail_underdog": {
                "model": "basic",
                "minimum_net_edge": 0.04,
                "maximum_seconds_left": 135,
                "maximum_selected_ask": 0.35,
                "maximum_absolute_z": 1.0,
                "side": "cheaper ask only",
            },
            "adaptive_volatility": {"model": "adaptive", "minimum_net_edge": 0.04},
            "market_agreement_band_001": {
                "source": "adaptive_volatility",
                "selected_ask": [0.30, 0.95],
                "maximum_raw_market_probability_gap": 0.08,
                "maximum_binary_spread": 0.02,
            },
            "market_anchor_conservative_001": {
                "source": "adaptive_volatility",
                "selected_ask": [0.30, 0.85],
                "maximum_raw_market_probability_gap": 0.06,
                "maximum_binary_spread": 0.01,
                "minimum_two_cent_stressed_edge": 0.0,
                "risk_layer": "conservative_anchor",
            },
            "moderate_disagreement_band_001": {
                "source": "adaptive_volatility",
                "selected_ask": [0.30, 0.50],
                "raw_market_probability_gap": [0.06, 0.08],
                "lower_gap_is_exclusive": True,
                "maximum_binary_spread": 0.01,
                "minimum_two_cent_stressed_edge": 0.0,
                "risk_layer": "conservative_anchor",
            },
        },
        "economics": {
            "reference_bankroll_dollars": "100.00",
            "maximum_all_in_cost_per_market_dollars": "1.00",
            "integer_contracts": True,
            "taker_fee": "ceil balance(cost + ceil_6dp(0.07*n*p*(1-p))) minus cost",
            "position_policy": "hold to official settlement",
            "base_entry_price": "selected-side decision candle close ask",
            "adverse_price_stress_dollars": ["0.01", "0.02"],
            "depth_or_fill_claim": False,
        },
        "conservative_anchor_risk_layer": {
            "cooldown_seconds": 3600,
            "daily_realized_loss_halt_dollars": "2.00",
            "daily_consecutive_loss_halt": 3,
            "maximum_realized_drawdown_dollars": "5.00",
        },
        "metrics": [
            "settlements",
            "wins",
            "fees",
            "net_pnl",
            "pnl_without_top_three_winners",
            "one_and_two_cent_stress",
            "positive_day_share",
            "five_chronological_blocks",
            "maximum_drawdown",
            "brier_score",
            "binary_log_loss",
            "rejection_counts",
        ],
        "advancement_gate": {
            "minimum_validation_settlements": 100,
            "minimum_validation_utc_dates": 20,
            "positive_net_pnl": True,
            "positive_without_top_three_winners": True,
            "positive_one_and_two_cent_stress": True,
            "positive_day_share_above": 0.5,
            "positive_in_four_of_five_blocks": True,
            "maximum_drawdown_at_most_dollars": "10.00",
        },
        "scope": "Read-only candle screen; no demo or production order authority and no executable-fill claim",
    }


def registration_hash():
    return hashlib.sha256(canonical(registration())).hexdigest()

