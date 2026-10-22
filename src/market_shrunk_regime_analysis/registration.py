from __future__ import annotations

import hashlib

from historical_backtest.registration import (
    SOURCE_AUDIT_SHA256,
    SOURCE_CHAIN_SHA256,
    SOURCE_DATABASE_SHA256,
)
from historical_market_confirmation.kelly_registration import SIGNAL
from research_lab.storage import canonical

STUDY = "025"
EXPECTED_FIXED_LEDGER = "149f874d7e98af5b4720b0b1ee7a489d8e05b7330db93bf45f74e7c9fae37773"
MINIMUM_PARTITION_BUCKET_TRADES = 20

FEATURES = {
    "side": ["yes", "no"],
    "entry_price": ["45-54", "55-64", "65-69", "70-74", "75-79"],
    "seconds_left": ["5-60", "61-120", "121-180", "181-240", "241-300"],
    "absolute_raw_market_gap": ["0-1.49", "1.5-2.99", "3-4.99", "5-7.5"],
    "modeled_net_edge": ["0.5-1.99", "2-3.99", "4-7.99", "8+"],
    "fast_slow_variance_ratio": ["0-0.49", "0.5-0.99", "1-1.99", "2+"],
    "selected_market_probability": ["20-34", "35-49", "50-64", "65-80"],
    "utc_hour": ["00-05", "06-11", "12-17", "18-23"],
    "chronological_block": ["1", "2", "3", "4", "5"],
}


def registration():
    return {
        "study": STUDY,
        "name": "market_shrunk_regime_failure_analysis_025",
        "declared_date": "2026-10-21",
        "objective": (
            "Identify repeatable sources of Study 023's stressed-period losses without changing its signal, "
            "selecting a production rule, or viewing the sealed holdout."
        ),
        "source": {
            "series": "KXBTC15M",
            "database_sha256": SOURCE_DATABASE_SHA256,
            "audit_sha256": SOURCE_AUDIT_SHA256,
            "event_chain_sha256": SOURCE_CHAIN_SHA256,
            "research_partition": "already-viewed oldest 80% used by Study 023",
            "holdout": "newest 20% remains locked and unevaluated",
            "study_023_fixed_1_trade_ledger_sha256": EXPECTED_FIXED_LEDGER,
        },
        "signal": SIGNAL,
        "risk": {
            "variant": "fixed $1 all-in maximum",
            "integer_contracts": True,
            "fees_inside_budget": True,
            "stress": "reprice the same quantity one and two cents adversely, including recalculated fee",
        },
        "diagnostic_features": FEATURES,
        "partition_rule": {
            "development_and_validation_reported_separately": True,
            "minimum_trades_per_partition_for_repeatable_label": MINIMUM_PARTITION_BUCKET_TRADES,
            "repeatable_weakness": "negative two-cent-stressed P&L in both partitions",
            "sign_instability": "opposite two-cent-stressed P&L signs across partitions",
        },
        "reporting": {
            "metrics": [
                "trades, wins and Wilson 90% win-rate interval",
                "mean entry price, fees and fixed-$1 net P&L",
                "one- and two-cent adverse-price P&L",
                "P&L without the three largest winners",
                "maximum drawdown and top-three-winner concentration",
                "development-versus-validation sign consistency",
                "five chronological block results and regime composition",
            ]
        },
        "interpretation": {
            "diagnostic_only": True,
            "no_automatic_filter_selection": True,
            "cannot_promote_or_change_production": True,
            "holdout_evaluated": False,
            "production_orders_authorized": False,
        },
    }


def registration_hash():
    return hashlib.sha256(canonical(registration())).hexdigest()
