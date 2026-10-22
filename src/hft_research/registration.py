"""Frozen research-only registration for Jev-gated HFT Study 028."""

from __future__ import annotations

import hashlib

from research_lab.storage import canonical

STUDY = "028"
JEV_MODEL = "jev-1.13.0"


def registration():
    return {
        "study": STUDY,
        "name": "jev_gated_hft_feasibility_028",
        "declared_date": "2026-10-22",
        "scope": {
            "series": "KXBTC15M",
            "exchange": "Predictions index 2",
            "research_only": True,
            "production_orders_authorized": False,
            "demo_orders_authorized": False,
        },
        "hypothesis": (
            "A deterministic settlement-aware quoting engine can identify positive expected spread or "
            "stale-quote opportunities, and a typed Jev veto can reduce adverse selection without creating "
            "new actions or erasing the baseline's profitability."
        ),
        "arms": {
            "A": "deterministic mathematical engine only",
            "B": "same engine plus Jev cancel/veto only",
            "C": "same engine plus Jev side restriction and taker permission",
        },
        "jev": {
            "model": JEV_MODEL,
            "version_is_pinned": True,
            "call_policy": "event-triggered and cached by canonical input digest",
            "allowed_outputs": [
                "regime",
                "quote_policy",
                "model_trust",
                "taker_allowed",
                "adverse_selection_risk",
            ],
            "may_create_action": False,
            "failure_policy": "cancel_all and taker disallowed",
        },
        "data_phases": {
            "existing_archive": (
                "evaluate fair value, quote opportunity, markout and Jev classification; do not claim maker fills"
            ),
            "new_forward_tape": (
                "record order-book, public trades, BRTI, local receipt time and exchange time for queue validation"
            ),
            "shadow": "emit intended actions without submitting orders",
            "demo": "requires a later explicit authorization after replay and shadow gates",
            "live": "requires a later explicit authorization after demo gates",
        },
        "execution_assumptions": {
            "maker_queue": "join back of displayed queue at acknowledgement",
            "cancellations_ahead": "do not advance simulated queue without an observable attribution rule",
            "partial_fills": True,
            "latency_stress_multipliers": [1, 2],
            "adverse_price_stress_cents": [1, 2],
        },
        "minimum_evidence_before_demo_review": {
            "distinct_utc_dates": 20,
            "plausible_simulated_fills": 1000,
            "positive_after_fees": True,
            "positive_under_conservative_queue_model": True,
            "positive_without_three_largest_winners": True,
            "required_positive_time_blocks": "4 of 5",
            "jev_requirement": (
                "improve out-of-sample net P&L or reduce adverse-selection loss/maximum drawdown by at least 20% "
                "without destroying practical fill frequency"
            ),
        },
        "initial_risk_if_later_authorized": {
            "unit": "one contract",
            "maximum_total_inventory_dollars": "5.00",
            "maximum_aggressive_positions": 1,
            "kelly_sizing": False,
        },
    }


def registration_hash():
    return hashlib.sha256(canonical(registration())).hexdigest()
