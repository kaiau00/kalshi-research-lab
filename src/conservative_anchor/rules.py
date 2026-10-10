from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from decimal import Decimal

from research_lab.engine import entry_fee
from research_lab.settings import Experiment
from research_lab.storage import canonical

STRATEGY = "market_anchor_conservative_001"
MIN_DECISION_PRICE = Decimal("0.30")
MAX_DECISION_PRICE = Decimal("0.85")
MAX_MODEL_MARKET_GAP = 0.06
MAX_BINARY_SPREAD = Decimal("0.01")
ADVERSE_PRICE_BUFFER = Decimal("0.02")
MIN_STRESSED_EDGE = 0.0
COOLDOWN_SECONDS = 3600
DAILY_LOSS_LIMIT = Decimal("2.00")
DAILY_CONSECUTIVE_LOSS_LIMIT = 3
MAXIMUM_REALIZED_DRAWDOWN = Decimal("5.00")


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
        edge = stressed_edge(trade, cfg)
    except (KeyError, TypeError, ValueError):
        return False
    if not all(math.isfinite(value) for value in (raw_yes, market_yes)) or edge is None:
        return False
    return bool(
        MIN_DECISION_PRICE <= price < MAX_DECISION_PRICE
        and 0 <= spread <= MAX_BINARY_SPREAD
        and abs(raw_yes - market_yes) <= MAX_MODEL_MARKET_GAP
        and edge >= MIN_STRESSED_EDGE
    )


def performance_guard(settlements, now_ns):
    """Return the frozen realized-risk state for records known by ``now_ns``."""
    now_day = datetime.fromtimestamp(now_ns / 1e9, timezone.utc).date().isoformat()
    known = sorted(
        (row for row in settlements if int(row["settled_ns"]) <= now_ns),
        key=lambda row: (int(row["settled_ns"]), row.get("ticker", "")),
    )
    equity = peak = Decimal(0)
    drawdown = Decimal(0)
    today = []
    for row in known:
        pnl = Decimal(str(row["pnl"]))
        equity += pnl
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
        if row["settled_day"] == now_day:
            today.append(pnl)
    daily_pnl = sum(today, Decimal(0))
    consecutive_losses = 0
    for pnl in reversed(today):
        if pnl >= 0:
            break
        consecutive_losses += 1
    reason = None
    if drawdown >= MAXIMUM_REALIZED_DRAWDOWN:
        reason = "maximum_realized_drawdown"
    elif daily_pnl <= -DAILY_LOSS_LIMIT:
        reason = "daily_loss_limit"
    elif consecutive_losses >= DAILY_CONSECUTIVE_LOSS_LIMIT:
        reason = "daily_consecutive_loss_limit"
    return {
        "reason": reason,
        "realized_pnl": str(equity),
        "maximum_realized_drawdown": str(drawdown),
        "utc_day": now_day,
        "daily_realized_pnl": str(daily_pnl),
        "daily_consecutive_losses": consecutive_losses,
        "settled_trades": len(known),
    }


def registration():
    return {
        "strategy": STRATEGY,
        "signal": {
            "source": "adaptive_volatility",
            "minimum_raw_modeled_net_edge": 0.04,
            "entry_window_seconds": [5, 300],
            "latency_ms": 500,
            "execution": "delayed_ioc",
        },
        "filters": {
            "minimum_selected_side_ask": str(MIN_DECISION_PRICE),
            "maximum_selected_side_ask_exclusive": str(MAX_DECISION_PRICE),
            "maximum_absolute_raw_vs_market_yes_probability_gap": MAX_MODEL_MARKET_GAP,
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
    }


def registration_hash():
    return hashlib.sha256(canonical(registration())).hexdigest()
