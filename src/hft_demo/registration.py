"""Frozen identity for deterministic HFT baseline Study 029."""

from __future__ import annotations

import hashlib

from research_lab.storage import canonical

STUDY = "029"
STRATEGY = "deterministic_binary_market_maker_001"
CONFIG_REVISION = "hft-baseline-demo-001-20261023"
AUTHORIZATION = "hft-demo-study-029-authorized-20261023"


def registration() -> dict:
    return {
        "study": STUDY,
        "strategy": STRATEGY,
        "declared_date": "2026-10-23",
        "scope": {
            "series": "KXBTC15M",
            "environment": "Kalshi Demo only",
            "exchange_index": 2,
            "subaccount": 0,
            "production_orders_authorized": False,
            "demo_orders_authorized": True,
        },
        "fair_value": {
            "settlement_model": "conditional Brownian average of the final 60 BRTI seconds",
            "variance": "70% trailing 60-second variance plus 30% trailing 600-second variance",
            "market_reference": "equal blend of two-sided midpoint and top-level microprice",
            "pool": "75% raw model plus 25% market reference in log-odds space",
            "maximum_raw_market_gap": 0.12,
        },
        "quoting": {
            "quantity": "one contract per quote",
            "time_window_seconds": [30, 300],
            "probability_range": [0.10, 0.90],
            "minimum_binary_spread": "0.02",
            "improve_only_when_spread_at_least": "0.04",
            "minimum_expected_edge_after_fee": "0.001",
            "adverse_selection_reserve": "0.001",
            "maker_fee_coefficient": "0.0175",
            "post_only": True,
            "replay_acknowledgement_latency_ms": 500,
            "quote_lifetime_seconds": 3,
            "refresh_interval_seconds": 1,
        },
        "inventory": {
            "utility": "exact CARA certainty equivalent for a binary terminal payoff",
            "absolute_risk_aversion": 0.02,
            "maximum_absolute_net_contracts": 5,
            "maximum_markets_with_inventory": 1,
            "maximum_resting_orders": 2,
            "maximum_gross_premium_dollars": "5.00",
            "kelly_sizing": False,
        },
        "safety": {
            "durable_intent_before_write": True,
            "automatic_post_retry": False,
            "unknown_create_or_cancel_blocks_new_orders": True,
            "cancel_on_pause": True,
            "cancel_before_close_seconds": 30,
            "external_order_or_position_blocks": True,
            "book_max_age_ms": 1500,
            "index_max_age_ms": 2500,
            "stop_file": "STOP",
            "pause_file": "PAUSE_QUOTES",
        },
        "jev": {
            "enabled": False,
            "rule": "Jev may be added only after the frozen mathematical baseline shows credible edge",
        },
    }


def registration_hash() -> str:
    return hashlib.sha256(canonical(registration())).hexdigest()

