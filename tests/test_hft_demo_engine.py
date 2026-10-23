from decimal import Decimal

import pytest

from hft_demo.engine import (
    Config,
    Level,
    Snapshot,
    certainty_equivalent,
    decide,
    maker_fee,
    pooled_probability,
    reservation_values,
)


def snapshot(**overrides):
    values = {
        "ticker": "KXBTC15M-TEST",
        "received_ns": 1_000_000_000,
        "seconds_left": 180,
        "raw_yes_probability": 0.50,
        "inventory": 0,
        "yes_bid": Level(Decimal("0.48"), Decimal("20")),
        "yes_ask": Level(Decimal("0.52"), Decimal("20")),
    }
    values.update(overrides)
    return Snapshot(**values)


def test_log_odds_pool_is_bounded_and_between_inputs():
    value = pooled_probability(0.70, 0.50, 0.25)
    assert 0.50 < value < 0.70
    assert pooled_probability(0.70, 0.50, 0) == pytest.approx(0.70)
    assert pooled_probability(0.70, 0.50, 1) == pytest.approx(0.50)


def test_binary_cara_inventory_skews_quotes_toward_flattening():
    assert certainty_equivalent(0, 0.5, 0.02) == 0
    flat_yes, flat_no = reservation_values(0, 0.5, 0.02)
    long_yes, long_no = reservation_values(4, 0.5, 0.02)
    assert flat_yes == pytest.approx(flat_no)
    assert long_yes < flat_yes
    assert long_no > flat_no


def test_baseline_emits_postable_quotes_with_fee_adjusted_edge():
    decision = decide(snapshot())
    assert {quote.outcome for quote in decision.quotes} == {"yes", "no"}
    assert all(quote.quantity == 1 for quote in decision.quotes)
    assert all(quote.expected_edge >= Decimal("0.001") for quote in decision.quotes)
    assert {quote.book_side for quote in decision.quotes} == {"bid", "ask"}


def test_inventory_cap_and_disagreement_fail_closed():
    decision = decide(snapshot(inventory=5))
    assert all(quote.outcome != "yes" for quote in decision.quotes)
    disagreed = decide(snapshot(raw_yes_probability=0.70))
    assert not disagreed.quotes
    assert "raw_market_disagreement" in disagreed.rejections


def test_time_probability_and_book_validation_fail_closed():
    assert not decide(snapshot(seconds_left=20)).quotes
    assert not decide(snapshot(raw_yes_probability=0.95)).quotes
    with pytest.raises(ValueError, match="crossed"):
        snapshot(yes_bid=Level(Decimal("0.52"), Decimal("1")))


def test_maker_fee_rounds_conservatively_to_direct_balance_precision():
    fee = maker_fee(Decimal("0.50"), 1)
    assert fee == Decimal("0.0044")
    assert maker_fee(Decimal("0.50"), 2) >= 2 * fee - Decimal("0.0001")


def test_one_cent_spread_is_rejected():
    cfg = Config(minimum_spread=Decimal("0.02"))
    decision = decide(
        snapshot(
            yes_bid=Level(Decimal("0.49"), Decimal("10")),
            yes_ask=Level(Decimal("0.50"), Decimal("10")),
        ),
        cfg,
    )
    assert not decision.quotes
    assert "no_fee_adjusted_passive_edge" in decision.rejections
