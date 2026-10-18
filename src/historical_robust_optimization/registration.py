from __future__ import annotations

import hashlib
import itertools

from historical_backtest.registration import (
    SOURCE_AUDIT_SHA256,
    SOURCE_CHAIN_SHA256,
    SOURCE_DATABASE_SHA256,
)
from research_lab.storage import canonical

STUDY = "020"
FAST_VARIANCE_WEIGHTS = (0.50, 0.70, 0.90)
PROBABILITY_MARKET_WEIGHTS = (0.0, 0.10)
MINIMUM_NET_EDGES = (0.02, 0.025, 0.03, 0.035)
PRICE_BANDS = (
    (0.45, 0.80),
    (0.45, 0.85),
    (0.50, 0.80),
    (0.50, 0.85),
    (0.50, 0.90),
    (0.55, 0.85),
    (0.55, 0.90),
    (0.60, 0.90),
)
MAXIMUM_MODEL_MARKET_GAPS = (0.05, 0.06, 0.075)
ENTRY_WINDOWS_SECONDS = ((5, 180), (5, 300), (30, 180), (30, 300))
MAXIMUM_BINARY_SPREADS = (0.01, 0.02)
MINIMUM_TWO_CENT_STRESSED_EDGES = (0.0,)

RISK_VARIANTS = {
    "fixed_1": {"kind": "fixed", "maximum_all_in_dollars": "1.00"},
    "fixed_1_50": {"kind": "fixed", "maximum_all_in_dollars": "1.50"},
    "fixed_2": {"kind": "fixed", "maximum_all_in_dollars": "2.00"},
    "fixed_3": {"kind": "fixed", "maximum_all_in_dollars": "3.00"},
    "sixteenth_kelly_cap_3": {
        "kind": "fractional_kelly",
        "multiplier": "0.0625",
        "cap": "3.00",
    },
    "eighth_kelly_cap_3": {
        "kind": "fractional_kelly",
        "multiplier": "0.125",
        "cap": "3.00",
    },
}


def configurations():
    rows = []
    axes = itertools.product(
        FAST_VARIANCE_WEIGHTS,
        PROBABILITY_MARKET_WEIGHTS,
        MINIMUM_NET_EDGES,
        PRICE_BANDS,
        MAXIMUM_MODEL_MARKET_GAPS,
        ENTRY_WINDOWS_SECONDS,
        MAXIMUM_BINARY_SPREADS,
        MINIMUM_TWO_CENT_STRESSED_EDGES,
    )
    for fast_weight, market_weight, edge, band, gap, window, spread, stressed_edge in axes:
        rows.append(
            {
                "name": (
                    f"v{int(fast_weight * 100):02d}_w{int(market_weight * 100):02d}_"
                    f"e{int(edge * 1000):03d}_p{int(band[0] * 100):02d}"
                    f"{int(band[1] * 100):02d}_g{int(gap * 1000):03d}_"
                    f"t{window[0]:03d}{window[1]:03d}_s{int(spread * 100):02d}_"
                    f"b{int(stressed_edge * 100):02d}"
                ),
                "fast_variance_weight": fast_weight,
                "probability_market_log_odds_weight": market_weight,
                "minimum_net_edge": edge,
                "minimum_selected_ask": band[0],
                "maximum_selected_ask_exclusive": band[1],
                "maximum_raw_model_market_gap": gap,
                "minimum_seconds_left": window[0],
                "maximum_seconds_left": window[1],
                "maximum_binary_spread": spread,
                "minimum_two_cent_stressed_edge": stressed_edge,
            }
        )
    return rows


def registration():
    return {
        "study": STUDY,
        "name": "historical_robust_parameter_risk_study_020",
        "declared_date": "2026-10-18",
        "source": {
            "series": "KXBTC15M",
            "database_sha256": SOURCE_DATABASE_SHA256,
            "audit_sha256": SOURCE_AUDIT_SHA256,
            "event_chain_sha256": SOURCE_CHAIN_SHA256,
            "research_partition": "the already-viewed first 80% from Studies 018 and 019",
            "holdout": "newest 20% from Study 018 remains locked and unevaluated",
        },
        "purpose": (
            "Search for a materially stronger and chronologically stable neighbor of the Study 019 "
            "lead without opening the holdout or letting larger sizing promote a weak signal."
        ),
        "grid": {
            "fast_variance_weights": list(FAST_VARIANCE_WEIGHTS),
            "probability_market_log_odds_weights": list(PROBABILITY_MARKET_WEIGHTS),
            "minimum_net_edges": list(MINIMUM_NET_EDGES),
            "selected_ask_bands": [list(value) for value in PRICE_BANDS],
            "maximum_raw_model_market_gaps": list(MAXIMUM_MODEL_MARKET_GAPS),
            "entry_windows_seconds": [list(value) for value in ENTRY_WINDOWS_SECONDS],
            "maximum_binary_spreads": list(MAXIMUM_BINARY_SPREADS),
            "minimum_two_cent_stressed_edges": list(MINIMUM_TWO_CENT_STRESSED_EDGES),
            "configuration_count": len(configurations()),
        },
        "signal_selection": {
            "primary_sizing": "fixed_1",
            "starting_bankroll_dollars": "100.00",
            "original_partitions": ["development", "validation"],
            "chronological_blocks": 5,
            "one_sided_daily_mean_confidence": 0.90,
            "ranking": [
                "all stronger-than-Study-019 gates",
                "higher worst two-cent-stressed block P&L",
                "higher original-validation two-cent-stressed P&L",
                "higher aggregate two-cent-stressed P&L",
                "higher P&L without the three largest winners",
                "lower maximum drawdown",
                "lexical configuration name",
            ],
        },
        "stronger_than_study_019_gate": {
            "minimum_settlements": 200,
            "minimum_base_pnl_exclusive": "11.9751",
            "minimum_pnl_without_top_three_exclusive": "10.5276",
            "minimum_two_cent_stressed_pnl_exclusive": "1.3466",
            "positive_one_cent_stress": True,
            "positive_on_majority_of_days": True,
            "positive_in_four_of_five_base_blocks": True,
            "positive_two_cent_stress_in_four_of_five_blocks": True,
            "maximum_drawdown_at_most_dollars": "10.00",
            "positive_development_base_ex_top_three_and_two_cent_stress": True,
            "positive_validation_base_ex_top_three_and_two_cent_stress": True,
            "minimum_validation_settlements": 75,
            "positive_one_sided_90pct_daily_mean_lower_bound": True,
        },
        "risk": {
            "variants": RISK_VARIANTS,
            "starting_bankroll_dollars": "100.00",
            "signal_selected_only_with_fixed_1": True,
            "integer_contracts": True,
            "fees_inside_budget": True,
            "stress_keeps_base_quantity": True,
            "recommendation_constraints": {
                "positive_two_cent_stress": True,
                "positive_without_top_three_winners": True,
                "maximum_drawdown_at_most_dollars": "10.00",
            },
            "recommendation_ranking": [
                "higher two-cent-stressed P&L divided by maximum drawdown",
                "higher two-cent-stressed P&L",
                "lower maximum drawdown",
                "lower mean target budget",
            ],
        },
        "interpretation": {
            "minute_candle_depth_or_fill_claim": False,
            "development_only": True,
            "holdout_evaluated": False,
            "production_orders_authorized": False,
            "multiple_testing_warning": (
                "A gate passer remains a research candidate until one untouched holdout evaluation and "
                "separate executable-book validation."
            ),
        },
    }


def registration_hash():
    return hashlib.sha256(canonical(registration())).hexdigest()
