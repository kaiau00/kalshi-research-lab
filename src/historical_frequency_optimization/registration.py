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

STUDY = "021"
FAST_VARIANCE_WEIGHTS = (0.60, 0.75, 0.90)
PROBABILITY_MARKET_WEIGHTS = (0.0, 0.10)
TREND_MULTIPLIERS = (-0.25, 0.0, 0.25, 0.50)
MINIMUM_NET_EDGES = (0.015, 0.020, 0.025, 0.030)
PRICE_BANDS = (
    (0.35, 0.75),
    (0.40, 0.75),
    (0.40, 0.80),
    (0.45, 0.80),
    (0.45, 0.85),
)
MAXIMUM_MODEL_MARKET_GAPS = (0.060, 0.075, 0.100)
ENTRY_WINDOWS_SECONDS = ((5, 180), (5, 300))
MAXIMUM_BINARY_SPREADS = (0.01, 0.02)
MAXIMUM_FAST_SLOW_VARIANCE_RATIOS = (None, 1.50)


def _label(value: float | None, scale: int = 1000) -> str:
    return "none" if value is None else f"{int(round(value * scale)):04d}"


def configurations():
    rows = []
    axes = itertools.product(
        FAST_VARIANCE_WEIGHTS,
        PROBABILITY_MARKET_WEIGHTS,
        TREND_MULTIPLIERS,
        MINIMUM_NET_EDGES,
        PRICE_BANDS,
        MAXIMUM_MODEL_MARKET_GAPS,
        ENTRY_WINDOWS_SECONDS,
        MAXIMUM_BINARY_SPREADS,
        MAXIMUM_FAST_SLOW_VARIANCE_RATIOS,
    )
    for fast, market, trend, edge, band, gap, window, spread, ratio in axes:
        rows.append(
            {
                "name": (
                    f"v{int(fast * 100):02d}_w{int(market * 100):02d}_"
                    f"d{int(round((trend + 1) * 100)):03d}_e{int(edge * 1000):03d}_"
                    f"p{int(band[0] * 100):02d}{int(band[1] * 100):02d}_"
                    f"g{int(gap * 1000):03d}_t{window[0]:03d}{window[1]:03d}_"
                    f"s{int(spread * 100):02d}_r{_label(ratio)}"
                ),
                "fast_variance_weight": fast,
                "probability_market_log_odds_weight": market,
                "trend_multiplier": trend,
                "trend_horizon_seconds": 60,
                "minimum_net_edge": edge,
                "minimum_selected_ask": band[0],
                "maximum_selected_ask_exclusive": band[1],
                "maximum_raw_model_market_gap": gap,
                "minimum_seconds_left": window[0],
                "maximum_seconds_left": window[1],
                "maximum_binary_spread": spread,
                "maximum_fast_slow_variance_ratio": ratio,
                "minimum_two_cent_stressed_edge": 0.0,
            }
        )
    return rows


def registration():
    return {
        "study": STUDY,
        "name": "historical_frequency_strategy_study_021",
        "declared_date": "2026-10-18",
        "source": {
            "series": "KXBTC15M",
            "database_sha256": SOURCE_DATABASE_SHA256,
            "audit_sha256": SOURCE_AUDIT_SHA256,
            "event_chain_sha256": SOURCE_CHAIN_SHA256,
            "development": "oldest 60% from Dataset 017",
            "validation": "next 20%; previously viewed and therefore only a development diagnostic",
            "holdout": "newest 20% remains locked and unevaluated",
        },
        "purpose": (
            "Find a higher-frequency fixed-$1 signal near ten trades per observed UTC day without "
            "trading win rate for negative expectancy or using risk to conceal a weak signal."
        ),
        "forecast_families": {
            "mean_reversion": "-0.25 times the trailing 60-second log-return drift",
            "neutral": "zero drift, matching the prior structural model",
            "mild_momentum": "+0.25 times the trailing 60-second log-return drift",
            "momentum": "+0.50 times the trailing 60-second log-return drift",
            "future_path": "apply the frozen per-second drift to each unobserved settlement second",
        },
        "grid": {
            "fast_variance_weights": list(FAST_VARIANCE_WEIGHTS),
            "probability_market_log_odds_weights": list(PROBABILITY_MARKET_WEIGHTS),
            "trend_multipliers": list(TREND_MULTIPLIERS),
            "minimum_net_edges": list(MINIMUM_NET_EDGES),
            "selected_ask_bands": [list(value) for value in PRICE_BANDS],
            "maximum_raw_model_market_gaps": list(MAXIMUM_MODEL_MARKET_GAPS),
            "entry_windows_seconds": [list(value) for value in ENTRY_WINDOWS_SECONDS],
            "maximum_binary_spreads": list(MAXIMUM_BINARY_SPREADS),
            "maximum_fast_slow_variance_ratios": list(MAXIMUM_FAST_SLOW_VARIANCE_RATIOS),
            "configuration_count": len(configurations()),
        },
        "development_selection": {
            "primary_sizing": "fixed_1",
            "starting_bankroll_dollars": "100.00",
            "minimum_average_trades_per_observed_day": 8.0,
            "maximum_average_trades_per_observed_day": 12.0,
            "minimum_win_rate": 0.65,
            "minimum_mean_entry_price": "0.45",
            "maximum_mean_entry_price": "0.72",
            "minimum_base_pnl_exclusive": "15.00",
            "minimum_pnl_without_top_three_exclusive": "10.00",
            "positive_one_and_two_cent_stress": True,
            "positive_on_majority_of_days": True,
            "positive_in_four_of_five_base_blocks": True,
            "positive_two_cent_stress_in_four_of_five_blocks": True,
            "maximum_drawdown_at_most_dollars": "10.00",
            "positive_one_sided_90pct_daily_mean_lower_bound": True,
            "ranking": [
                "all development gates",
                "higher worst two-cent-stressed block P&L",
                "higher two-cent-stressed P&L",
                "higher P&L without the three largest winners",
                "closer to ten trades per day",
                "lower maximum drawdown",
                "lexical configuration name",
            ],
        },
        "validation_gate": {
            "same_8_to_12_average_trades_per_day_band": True,
            "minimum_win_rate": 0.65,
            "mean_entry_price_between": ["0.45", "0.72"],
            "positive_base_ex_top_three_one_cent_and_two_cent_pnl": True,
            "positive_on_majority_of_days": True,
            "positive_in_three_of_five_base_blocks": True,
            "positive_two_cent_stress_in_three_of_five_blocks": True,
            "maximum_drawdown_at_most_dollars": "5.00",
        },
        "aggregate_promotion_gate": {
            "minimum_base_pnl_exclusive": "24.4806",
            "minimum_pnl_without_top_three_exclusive": "21.2847",
            "minimum_two_cent_stressed_pnl_exclusive": "9.2233",
            "positive_in_four_of_five_base_and_two_cent_stress_blocks": True,
            "maximum_drawdown_at_most_dollars": "10.00",
            "positive_one_sided_90pct_daily_mean_lower_bound": True,
        },
        "risk": {
            "variants": RISK_VARIANTS,
            "opens_only_if_development_validation_and_aggregate_gates_pass": True,
            "integer_contracts": True,
            "fees_inside_budget": True,
            "stress_keeps_base_quantity": True,
        },
        "interpretation": {
            "minute_candle_depth_or_fill_claim": False,
            "development_only": True,
            "holdout_evaluated": False,
            "production_orders_authorized": False,
            "multiple_testing_warning": (
                "The validation slice has been viewed by earlier studies. A winner still requires the one "
                "untouched holdout evaluation and a separate executable-book forward study."
            ),
        },
    }


def registration_hash():
    return hashlib.sha256(canonical(registration())).hexdigest()
