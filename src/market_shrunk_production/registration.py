from __future__ import annotations

import hashlib

from historical_market_confirmation.kelly_registration import SIGNAL
from research_lab.storage import canonical

STRATEGY = "market_shrunk_half_kelly_001"
CONFIG_REVISION = "market-shrunk-half-kelly-production-001-20261019"
RISK_REVISION = "market-shrunk-half-kelly-risk-001-20261019"
HOLD_REVISION = "market-shrunk-half-kelly-hold-001-20261019"
FUNDING_REVISION = "market-shrunk-half-kelly-funding-002-20261019"
SOURCE_STUDY_REGISTRATION_SHA256 = (
    "7314ad94911093b14a8fd33168240e0a789aa4a04727f677faaae6ee5fa2b5d0"
)
AUTHORIZATION = "real-btc-15m-market-shrunk-half-kelly-001-2026-10-19"
RISK_AUTHORIZATION = "real-btc-15m-market-shrunk-half-kelly-risk-001-2026-10-19"
HOLD_AUTHORIZATION = "real-btc-15m-market-shrunk-half-kelly-hold-001-2026-10-19"


def registration():
    return {
        "strategy": STRATEGY,
        "authorized_on": "2026-10-19",
        "authorization_scope": (
            "The user explicitly requested live real-money execution of the Study 023 lead "
            "with one-half Kelly sizing, then explicitly authorized exactly $140 of internal "
            "Predictions funding and bot activation."
        ),
        "source": {
            "study": "023",
            "risk_diagnostic": "024",
            "study_024_registration_sha256": SOURCE_STUDY_REGISTRATION_SHA256,
            "signal": SIGNAL,
            "warning": (
                "Study 023 failed its preregistered validation drawdown and stressed-block gates."
            ),
        },
        "account": {
            "series": "KXBTC15M",
            "exchange_index": 2,
            "subaccount": 0,
            "required_initial_cash_dollars": "140.0000",
            "funding_revision": FUNDING_REVISION,
        },
        "decision": {
            "clock": "once just after each completed UTC minute boundary",
            "raw_probability": "90% 60-second variance plus 10% 600-second variance",
            "probability": "75% raw model plus 25% Kalshi midpoint in log-odds space",
            "selected_side_ask": ["0.45 inclusive", "0.80 exclusive"],
            "minimum_net_edge": "0.005",
            "maximum_raw_model_market_gap": "0.075",
            "maximum_binary_spread": "0.02",
            "minimum_two_cent_stressed_edge": "0.00",
            "seconds_left": [5, 300],
            "attempts": "one signal and at most one IOC submission per market",
        },
        "risk": {
            "revision": RISK_REVISION,
            "sizing": "one-half full Kelly",
            "full_kelly": "(modeled_probability - one_contract_all_in_cost) / (1 - one_contract_all_in_cost)",
            "bankroll": "current exchange-index-2 cash after every official settlement",
            "maximum_all_in_entry_cost": "3.00",
            "integer_contracts": True,
            "fees_inside_budget": True,
            "no_daily_stop_or_cooldown": True,
        },
        "execution": {
            "revision": CONFIG_REVISION,
            "arrival_delay_ms": 500,
            "order_type": "immediate_or_cancel",
            "maximum_quantity": "displayed integer depth at the best eligible arrival level",
            "automatic_post_retry": False,
            "block_on_unknown_order_or_account_exposure": True,
            "fresh_ledger": "/data/production-market-shrunk-half-kelly-001",
            "fresh_ledger_starts_paused": True,
        },
        "position": {
            "revision": HOLD_REVISION,
            "policy": "hold to official settlement",
            "early_exit_submission": "disabled",
        },
    }


def registration_hash():
    return hashlib.sha256(canonical(registration())).hexdigest()
