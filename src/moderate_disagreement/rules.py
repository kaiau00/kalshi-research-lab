from __future__ import annotations

import hashlib
import math
from decimal import Decimal

from conservative_anchor.rules import (
    COOLDOWN_SECONDS,
    DAILY_CONSECUTIVE_LOSS_LIMIT,
    DAILY_LOSS_LIMIT,
    MAXIMUM_REALIZED_DRAWDOWN,
)
from research_lab.engine import entry_fee
from research_lab.settings import Experiment
from research_lab.storage import canonical

STRATEGY = "moderate_disagreement_band_001"
MIN_DECISION_PRICE = Decimal("0.30")
MAX_DECISION_PRICE = Decimal("0.50")
MIN_MODEL_MARKET_GAP_EXCLUSIVE = 0.06
MAX_MODEL_MARKET_GAP = 0.08
MAX_BINARY_SPREAD = Decimal("0.01")
ADVERSE_PRICE_BUFFER = Decimal("0.02")
MIN_STRESSED_EDGE = 0.0


def selected_probability(trade):
    raw_yes = float(trade["forecast"]["yes_probability"])
    return raw_yes if trade["side"] == "yes" else 1 - raw_yes


def stressed_edge(trade, cfg=None):
    cfg = cfg or Experiment()
    price = Decimal(str(trade["limit"])) + ADVERSE_PRICE_BUFFER
    if price >= 1:
        return None
    return selected_probability(trade) - float(price + entry_fee(price, 1, cfg))


def qualifies(trade, cfg=None):
    try:
        price = Decimal(str(trade["limit"]))
        spread = Decimal(str(trade["quoted_binary_spread"]))
        raw_yes = float(trade["forecast"]["yes_probability"])
        market_yes = float(trade["market_yes_probability"])
        gap = abs(raw_yes - market_yes)
        edge = stressed_edge(trade, cfg)
    except (KeyError, TypeError, ValueError):
        return False
    if not all(math.isfinite(value) for value in (raw_yes, market_yes, gap)) or edge is None:
        return False
    return bool(
        MIN_DECISION_PRICE <= price < MAX_DECISION_PRICE
        and 0 <= spread <= MAX_BINARY_SPREAD
        and gap > MIN_MODEL_MARKET_GAP_EXCLUSIVE + 1e-12
        and gap <= MAX_MODEL_MARKET_GAP + 1e-12
        and edge >= MIN_STRESSED_EDGE
    )


def registration():
    return {
        "strategy": STRATEGY,
        "signal": {
            "source": "adaptive_baseline_candidate_study_003",
            "minimum_raw_modeled_net_edge": 0.04,
            "entry_window_seconds": [5, 300],
            "latency_ms": 500,
            "execution": "recorded_delayed_ioc",
        },
        "filters": {
            "minimum_selected_side_ask": str(MIN_DECISION_PRICE),
            "maximum_selected_side_ask_exclusive": str(MAX_DECISION_PRICE),
            "minimum_absolute_raw_vs_market_gap_exclusive": MIN_MODEL_MARKET_GAP_EXCLUSIVE,
            "maximum_absolute_raw_vs_market_gap_inclusive": MAX_MODEL_MARKET_GAP,
            "maximum_binary_spread": str(MAX_BINARY_SPREAD),
            "adverse_price_buffer": str(ADVERSE_PRICE_BUFFER),
            "minimum_edge_after_adverse_price_and_fee": MIN_STRESSED_EDGE,
        },
        "risk": {
            "fixed_maximum_all_in_entry_cost": "1.00",
            "cooldown_seconds_after_fill": COOLDOWN_SECONDS,
            "daily_realized_loss_limit": str(DAILY_LOSS_LIMIT),
            "daily_consecutive_loss_limit": DAILY_CONSECUTIVE_LOSS_LIMIT,
            "maximum_realized_drawdown": str(MAXIMUM_REALIZED_DRAWDOWN),
        },
        "position_policy": "hold_to_official_settlement",
        "early_exit_submission": "disabled",
        "order_submission": "absent",
    }


def registration_hash():
    return hashlib.sha256(canonical(registration())).hexdigest()
