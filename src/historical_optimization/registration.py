from __future__ import annotations

import hashlib
import itertools

from historical_backtest.registration import (
    SOURCE_AUDIT_SHA256,
    SOURCE_CHAIN_SHA256,
    SOURCE_DATABASE_SHA256,
)
from research_lab.storage import canonical

STUDY = "019"
PROBABILITY_MARKET_WEIGHTS = (0.0, 0.25, 0.50)
MINIMUM_NET_EDGES = (0.03, 0.04, 0.05)
PRICE_BANDS = ((0.30, 0.70), (0.30, 0.85), (0.40, 0.75), (0.40, 0.80), (0.50, 0.85))
MAXIMUM_MODEL_MARKET_GAPS = (0.03, 0.045, 0.06)
MAXIMUM_SECONDS_LEFT = (120, 180, 300)
MAXIMUM_BINARY_SPREADS = (0.01, 0.02)
MINIMUM_TWO_CENT_STRESSED_EDGES = (0.0, 0.02)
SIZING_VARIANTS = {
    "fixed_1": {"kind": "fixed", "maximum_all_in_dollars": "1.00"},
    "fixed_3": {"kind": "fixed", "maximum_all_in_dollars": "3.00"},
    "eighth_kelly_cap_3": {"kind": "fractional_kelly", "multiplier": "0.125", "cap": "3.00"},
    "quarter_kelly_cap_3": {"kind": "fractional_kelly", "multiplier": "0.25", "cap": "3.00"},
    "half_kelly_cap_3": {"kind": "fractional_kelly", "multiplier": "0.50", "cap": "3.00"},
}


def configurations():
    rows = []
    axes = itertools.product(
        PROBABILITY_MARKET_WEIGHTS,
        MINIMUM_NET_EDGES,
        PRICE_BANDS,
        MAXIMUM_MODEL_MARKET_GAPS,
        MAXIMUM_SECONDS_LEFT,
        MAXIMUM_BINARY_SPREADS,
        MINIMUM_TWO_CENT_STRESSED_EDGES,
    )
    for weight, edge, band, gap, seconds, spread, stressed_edge in axes:
        rows.append(
            {
                "name": (
                    f"w{int(weight * 100):02d}_e{int(edge * 1000):03d}_"
                    f"p{int(band[0] * 100):02d}{int(band[1] * 100):02d}_"
                    f"g{int(gap * 1000):03d}_t{seconds}_s{int(spread * 100):02d}_"
                    f"b{int(stressed_edge * 100):02d}"
                ),
                "probability_market_log_odds_weight": weight,
                "minimum_net_edge": edge,
                "minimum_selected_ask": band[0],
                "maximum_selected_ask_exclusive": band[1],
                "maximum_raw_model_market_gap": gap,
                "maximum_seconds_left": seconds,
                "maximum_binary_spread": spread,
                "minimum_two_cent_stressed_edge": stressed_edge,
            }
        )
    return rows


def registration():
    return {
        "study": STUDY,
        "name": "historical_parameter_kelly_study_019",
        "declared_date": "2026-10-15",
        "source": {
            "series": "KXBTC15M",
            "database_sha256": SOURCE_DATABASE_SHA256,
            "audit_sha256": SOURCE_AUDIT_SHA256,
            "event_chain_sha256": SOURCE_CHAIN_SHA256,
            "research_partition": "the already-viewed first 80% from Study 018",
            "holdout": "newest 20% from Study 018 remains locked",
        },
        "model": {
            "raw_probability": "Study 018 adaptive 70% 60-second plus 30% 600-second variance",
            "probability_blend": "linear interpolation of raw and Kalshi midpoint log odds",
            "decision_clock": "completed one-minute candle ends, first qualifying decision consumes market",
            "benchmark_cutoff": "top-of-second BRTI through decision second minus one",
        },
        "grid": {
            "probability_market_log_odds_weights": list(PROBABILITY_MARKET_WEIGHTS),
            "minimum_net_edges": list(MINIMUM_NET_EDGES),
            "selected_ask_bands": [list(value) for value in PRICE_BANDS],
            "maximum_raw_model_market_gaps": list(MAXIMUM_MODEL_MARKET_GAPS),
            "maximum_seconds_left": list(MAXIMUM_SECONDS_LEFT),
            "maximum_binary_spreads": list(MAXIMUM_BINARY_SPREADS),
            "minimum_two_cent_stressed_edges": list(MINIMUM_TWO_CENT_STRESSED_EDGES),
            "configuration_count": len(configurations()),
        },
        "signal_selection": {
            "primary_sizing": "fixed_1",
            "starting_bankroll_dollars": "100.00",
            "no_cooldown_or_path_dependent_stop": True,
            "reason": "prove the signal before testing whether sizing changes its payoff",
            "five_blocks": "five contiguous blocks of the complete research-market chronology",
            "ranking": [
                "all advancement gates",
                "higher minimum block P&L",
                "higher P&L without top three winners",
                "higher two-cent stressed P&L",
                "lower maximum drawdown",
                "more settlements",
                "lexical configuration name",
            ],
        },
        "sizing": {
            "variants": SIZING_VARIANTS,
            "starting_bankroll_dollars": "100.00",
            "kelly_formula": "max(0, (selected_probability - one_contract_all_in_cost) / (1 - one_contract_all_in_cost))",
            "kelly_bankroll": "current cash before each sequential decision",
            "integer_contracts": True,
            "fees_inside_budget": True,
            "zero_size_is_no_trade": True,
            "stress": "hold base quantities fixed and add one or two cents to entry price",
            "sizing_cannot_promote_a_signal_that_fails_the_fixed_1_gate": True,
        },
        "advancement_gate": {
            "minimum_settlements": 100,
            "positive_net_pnl": True,
            "positive_without_top_three_winners": True,
            "positive_one_and_two_cent_stress": True,
            "positive_day_share_above": 0.5,
            "positive_in_four_of_five_market_time_blocks": True,
            "maximum_drawdown_at_most_dollars": "10.00",
        },
        "interpretation": {
            "minute_candle_depth_or_fill_claim": False,
            "multiple_testing_warning": "grid winners remain research hypotheses until the locked holdout",
            "holdout_open_rule": "only a frozen fixed_1 gate-passing signal may be evaluated once",
            "production_orders_authorized": False,
        },
    }


def registration_hash():
    return hashlib.sha256(canonical(registration())).hexdigest()
