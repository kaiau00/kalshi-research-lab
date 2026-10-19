from __future__ import annotations

import hashlib
import itertools

from historical_backtest.registration import (
    SOURCE_AUDIT_SHA256,
    SOURCE_CHAIN_SHA256,
    SOURCE_DATABASE_SHA256,
)
from historical_robust_optimization.registration import RISK_VARIANTS
from research_lab.storage import canonical

STUDY = "022"
FAST_VARIANCE_WEIGHTS = (0.60, 0.75, 0.90)
PROBABILITY_MARKET_WEIGHTS = (0.15, 0.25, 0.35)
QUOTE_CONFIRMATIONS = ("none", "nonnegative_selected_side_move", "one_cent_selected_side_move")
MINIMUM_NET_EDGES = (0.005, 0.010, 0.015)
PRICE_BANDS = ((0.40, 0.75), (0.45, 0.80), (0.45, 0.85))
MAXIMUM_MODEL_MARKET_GAPS = (0.075, 0.100, 0.125)
ENTRY_WINDOWS_SECONDS = ((5, 180), (5, 300))
MAXIMUM_BINARY_SPREADS = (0.01, 0.02)
MINIMUM_TWO_CENT_STRESSED_EDGES = (0.0, 0.01)
MAXIMUM_FAST_SLOW_VARIANCE_RATIOS = (None, 1.50)


def configurations():
    rows = []
    axes = itertools.product(
        FAST_VARIANCE_WEIGHTS,
        PROBABILITY_MARKET_WEIGHTS,
        QUOTE_CONFIRMATIONS,
        MINIMUM_NET_EDGES,
        PRICE_BANDS,
        MAXIMUM_MODEL_MARKET_GAPS,
        ENTRY_WINDOWS_SECONDS,
        MAXIMUM_BINARY_SPREADS,
        MINIMUM_TWO_CENT_STRESSED_EDGES,
        MAXIMUM_FAST_SLOW_VARIANCE_RATIOS,
    )
    for fast, market, confirmation, edge, band, gap, window, spread, buffer, ratio in axes:
        rows.append(
            {
                "name": (
                    f"v{int(fast * 100):02d}_w{int(market * 100):02d}_q{QUOTE_CONFIRMATIONS.index(confirmation)}_"
                    f"e{int(edge * 1000):03d}_p{int(band[0] * 100):02d}{int(band[1] * 100):02d}_"
                    f"g{int(gap * 1000):03d}_t{window[0]:03d}{window[1]:03d}_"
                    f"s{int(spread * 100):02d}_b{int(buffer * 100):02d}_"
                    f"r{'none' if ratio is None else int(ratio * 100)}"
                ),
                "fast_variance_weight": fast,
                "probability_market_log_odds_weight": market,
                "quote_confirmation": confirmation,
                "trend_multiplier": 0.0,
                "minimum_net_edge": edge,
                "minimum_selected_ask": band[0],
                "maximum_selected_ask_exclusive": band[1],
                "maximum_raw_model_market_gap": gap,
                "minimum_seconds_left": window[0],
                "maximum_seconds_left": window[1],
                "maximum_binary_spread": spread,
                "minimum_two_cent_stressed_edge": buffer,
                "maximum_fast_slow_variance_ratio": ratio,
            }
        )
    return rows


def registration():
    return {
        "study": STUDY,
        "name": "historical_market_confirmation_study_022",
        "declared_date": "2026-10-18",
        "source": {
            "series": "KXBTC15M",
            "database_sha256": SOURCE_DATABASE_SHA256,
            "audit_sha256": SOURCE_AUDIT_SHA256,
            "event_chain_sha256": SOURCE_CHAIN_SHA256,
            "development": "oldest 60% from Dataset 017",
            "validation": "next 20%; previously viewed and used only after development selection",
            "holdout": "newest 20% remains locked and unevaluated",
        },
        "purpose": (
            "Test whether stronger shrinkage toward Kalshi and completed-minute quote confirmation can support "
            "8–12 fixed-$1 trades per day without Study 021's stressed losses and drawdown."
        ),
        "strategies": {
            "market_shrinkage": (
                "pool the structural probability with 15%, 25% or 35% Kalshi midpoint weight in log-odds space"
            ),
            "quote_confirmation": {
                "none": "no quote-direction condition",
                "nonnegative_selected_side_move": (
                    "the selected side's midpoint probability has not fallen since the prior completed minute"
                ),
                "one_cent_selected_side_move": (
                    "the selected side's midpoint probability rose at least one cent since the prior completed minute"
                ),
            },
        },
        "grid": {
            "fast_variance_weights": list(FAST_VARIANCE_WEIGHTS),
            "probability_market_log_odds_weights": list(PROBABILITY_MARKET_WEIGHTS),
            "quote_confirmations": list(QUOTE_CONFIRMATIONS),
            "minimum_net_edges": list(MINIMUM_NET_EDGES),
            "selected_ask_bands": [list(value) for value in PRICE_BANDS],
            "maximum_raw_model_market_gaps": list(MAXIMUM_MODEL_MARKET_GAPS),
            "entry_windows_seconds": [list(value) for value in ENTRY_WINDOWS_SECONDS],
            "maximum_binary_spreads": list(MAXIMUM_BINARY_SPREADS),
            "minimum_two_cent_stressed_edges": list(MINIMUM_TWO_CENT_STRESSED_EDGES),
            "maximum_fast_slow_variance_ratios": list(MAXIMUM_FAST_SLOW_VARIANCE_RATIOS),
            "configuration_count": len(configurations()),
        },
        "gates": {
            "development": "identical to Study 021",
            "validation": "identical to Study 021",
            "aggregate": "must exceed Study 020 near miss, identical to Study 021",
            "frequency": "8–12 trades per every observed UTC day, including zero-trade days",
            "minimum_win_rate": 0.65,
            "mean_entry_price_between": ["0.45", "0.72"],
        },
        "risk": {
            "variants": RISK_VARIANTS,
            "opens_only_after_all_fixed_1_gates": True,
        },
        "interpretation": {
            "development_only": True,
            "minute_candle_depth_or_fill_claim": False,
            "holdout_evaluated": False,
            "production_orders_authorized": False,
            "multiple_testing_warning": (
                "A pass still needs the untouched final holdout and executable-book forward validation."
            ),
        },
    }


def registration_hash():
    return hashlib.sha256(canonical(registration())).hexdigest()
