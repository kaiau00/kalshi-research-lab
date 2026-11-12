"""Lock the published Polymarket US fee rounding used by the edge sweep."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research" / "polymarket-us-edge-sweep" / "scripts"))

from common import PRIMARY_CLIP, THETA_RETAIL, bankers_cent, per_contract_pnl, taker_fee


def test_bankers_rounding_examples_from_the_fee_schedule() -> None:
    assert bankers_cent(Decimal("0.025")) == Decimal("0.02")
    assert bankers_cent(Decimal("0.035")) == Decimal("0.04")


def test_tier4_hundred_lot_at_even_money_matches_the_published_max() -> None:
    # Fee schedule: Tier 4 theta 0.0695, 100 contracts at 0.50, fee $1.74.
    assert taker_fee(Decimal("0.0695"), 100, Decimal("0.50")) == Decimal("1.74")


def test_retail_favorite_fee_does_not_round_away_on_a_25_lot() -> None:
    # 0.095 * 25 * 0.95 * 0.05 = 0.1128125, which is 11 cents, not zero.
    assert taker_fee(THETA_RETAIL, PRIMARY_CLIP, Decimal("0.95")) == Decimal("0.11")
    # A one-lot at the same price rounds to zero. That column must not be the primary.
    assert taker_fee(THETA_RETAIL, 1, Decimal("0.95")) == Decimal("0.00")


def test_losing_favorite_is_negative_after_the_fee() -> None:
    pnl = per_contract_pnl(Decimal(0), Decimal("0.90"), THETA_RETAIL, PRIMARY_CLIP)
    assert pnl < Decimal("-0.90")
