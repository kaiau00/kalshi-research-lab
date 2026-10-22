from __future__ import annotations

import hashlib

from historical_backtest.registration import (
    SOURCE_AUDIT_SHA256,
    SOURCE_CHAIN_SHA256,
    SOURCE_DATABASE_SHA256,
)
from historical_market_confirmation.kelly_registration import SIGNAL
from research_lab.storage import canonical

STUDY = "026"
EXCLUDED_PRICE_MINIMUM = "0.65"
EXCLUDED_PRICE_MAXIMUM_EXCLUSIVE = "0.70"
EXPECTED_STUDY_023_LEDGER = "149f874d7e98af5b4720b0b1ee7a489d8e05b7330db93bf45f74e7c9fae37773"
EXPECTED_FILTERED_UNSEALED_LEDGER = (
    "a56172fdf61f214d15593705cec1034794b1d0160480e55643e10ed62724407b"
)
STUDY_025_REGISTRATION_SHA256 = "d2e224451786f24d24d1f4a6045de0d9705b8c69897ed4e41d317654bd561a94"
STUDY_025_REPORT_SHA256 = "9cd054f0f63b1fc66c93387f51964a81ef5726068644626f55f20b45680610ba"


def registration():
    return {
        "study": STUDY,
        "name": "market_shrunk_price_band_holdout_026",
        "declared_date": "2026-10-21",
        "objective": (
            "Evaluate one frozen Study 025 candidate once on Dataset 017's previously sealed newest 20%."
        ),
        "source": {
            "series": "KXBTC15M",
            "database_sha256": SOURCE_DATABASE_SHA256,
            "audit_sha256": SOURCE_AUDIT_SHA256,
            "event_chain_sha256": SOURCE_CHAIN_SHA256,
            "selection_source": "Study 025's already-viewed development and validation analysis",
            "study_025_registration_sha256": STUDY_025_REGISTRATION_SHA256,
            "study_025_report_sha256": STUDY_025_REPORT_SHA256,
            "holdout": "newest 20% of Dataset 017, unopened when this registration was committed",
        },
        "candidate": {
            "base_signal": SIGNAL,
            "first_base_signal_consumes_market": True,
            "filter": (
                "discard the market when the base signal's first selected-side ask is at least 0.65 and below "
                "0.70; do not search later minutes for another entry"
            ),
            "excluded_selected_ask": [
                EXCLUDED_PRICE_MINIMUM,
                EXCLUDED_PRICE_MAXIMUM_EXCLUSIVE,
            ],
            "expected_study_023_fixed_1_ledger_sha256": EXPECTED_STUDY_023_LEDGER,
            "expected_filtered_unsealed_fixed_1_ledger_sha256": EXPECTED_FILTERED_UNSEALED_LEDGER,
        },
        "economics": {
            "sizing": "fixed $1 maximum all-in per market",
            "integer_contracts": True,
            "fees_inside_budget": True,
            "position_policy": "hold to official settlement",
            "adverse_price_stress_cents": [1, 2],
            "historical_depth_or_fill_claim": False,
        },
        "holdout_gates": {
            "minimum_settled_trades": 100,
            "minimum_observed_utc_dates": 20,
            "minimum_trades_per_observed_day": 3.0,
            "minimum_win_rate": 0.65,
            "positive_net_pnl": True,
            "positive_pnl_without_top_three_winners": True,
            "positive_one_and_two_cent_stressed_pnl": True,
            "positive_day_share_above": 0.5,
            "positive_base_and_two_cent_stressed_blocks": 4,
            "maximum_drawdown_dollars": "5.00",
            "positive_one_sided_90pct_daily_mean_lower_bound": True,
        },
        "execution_guard": {
            "explicit_unlock_flag_required": True,
            "output_must_not_already_exist": True,
            "one_candidate_only": True,
            "no_parameter_search": True,
        },
        "interpretation": {
            "passing_does_not_prove_executable_fills": True,
            "passing_requires_new_executable_book_forward_validation": True,
            "risk_sizing_opens": False,
            "production_orders_authorized": False,
            "production_change_authorized": False,
        },
    }


def registration_hash():
    return hashlib.sha256(canonical(registration())).hexdigest()
