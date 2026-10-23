from decimal import Decimal

import pytest

from hft_research.queue import (
    QueueState,
    QuoteAcknowledgement,
    TradeObservation,
    apply_public_trade,
    maker_outcome,
    maker_price,
    timeline_relation,
)
from hft_research.tape import parse_public_trade


def quote(**overrides):
    values = {
        "ticker": "KXBTC15M-TEST",
        "outcome": "yes",
        "price": Decimal("0.42"),
        "quantity": Decimal("3"),
        "displayed_ahead": Decimal("5"),
        "exchange_ms": 1_000,
        "received_ns": 1_000_000_000,
    }
    values.update(overrides)
    return QuoteAcknowledgement(**values)


def trade(**overrides):
    values = {
        "trade_id": "trade-1",
        "ticker": "KXBTC15M-TEST",
        "yes_price": Decimal("0.42"),
        "no_price": Decimal("0.58"),
        "count": Decimal("3"),
        "taker_outcome": "no",
        "is_block": False,
        "exchange_ms": 1_001,
        "received_ns": 1_001_000_000,
    }
    values.update(overrides)
    return TradeObservation(**values)


def test_direction_and_price_map_to_opposite_passive_outcome():
    yes_maker = trade(taker_outcome="no")
    assert maker_outcome(yes_maker) == "yes"
    assert maker_price(yes_maker) == Decimal("0.42")
    no_maker = trade(taker_outcome="yes")
    assert maker_outcome(no_maker) == "no"
    assert maker_price(no_maker) == Decimal("0.58")


def test_validated_tape_trade_converts_without_reinterpreting_fields():
    frame = {
        "type": "trade",
        "msg": {
            "trade_id": "trade-validated",
            "market_ticker": "KXBTC15M-TEST",
            "yes_price_dollars": "0.4200",
            "no_price_dollars": "0.5800",
            "count_fp": "2.50",
            "taker_outcome_side": "no",
            "taker_book_side": "ask",
            "is_block_trade": False,
            "ts_ms": 1001,
        },
    }
    parsed = parse_public_trade(frame, {"KXBTC15M-TEST"})
    observed = TradeObservation.from_parsed(parsed, 1_001_000_000)
    assert observed == trade(
        trade_id="trade-validated",
        count=Decimal("2.50"),
    )
    frame["msg"]["taker_book_side"] = "bid"
    parsed = parse_public_trade(frame, {"KXBTC15M-TEST"})
    with pytest.raises(ValueError, match="direction fields disagree"):
        TradeObservation.from_parsed(parsed, 1_001_000_000)


def test_queue_advances_then_partially_and_fully_fills():
    state = QueueState.join_back(quote())
    first = apply_public_trade(state, trade(count=Decimal("3")))
    assert first.disposition == "advanced_queue"
    assert first.state.quantity_ahead == Decimal("2")
    assert first.state.filled == 0

    second = apply_public_trade(
        first.state,
        trade(trade_id="trade-2", count=Decimal("4"), exchange_ms=1_002, received_ns=1_002_000_000),
    )
    assert second.disposition == "filled"
    assert second.consumed_ahead == Decimal("2")
    assert second.filled == Decimal("2")
    assert second.state.remaining == Decimal("1")

    third = apply_public_trade(
        second.state,
        trade(trade_id="trade-3", count=Decimal("9"), exchange_ms=1_003, received_ns=1_003_000_000),
    )
    assert third.filled == Decimal("1")
    assert third.state.remaining == 0


@pytest.mark.parametrize(
    ("candidate", "disposition"),
    [
        (trade(is_block=True), "block_trade"),
        (trade(taker_outcome="yes"), "opposite_queue"),
        (trade(yes_price=Decimal("0.41"), no_price=Decimal("0.59")), "other_price"),
        (trade(ticker="KXBTC15M-OTHER"), "other_market"),
    ],
)
def test_ineligible_trades_never_advance_queue(candidate, disposition):
    state = QueueState.join_back(quote())
    update = apply_public_trade(state, candidate)
    assert update.disposition == disposition
    assert update.state == state


def test_cross_stream_timing_must_agree_strictly():
    acknowledgement = quote()
    assert timeline_relation(acknowledgement, trade()) == "after"
    before = trade(exchange_ms=999, received_ns=999_000_000)
    assert timeline_relation(acknowledgement, before) == "before"
    same_exchange_ms = trade(exchange_ms=1_000)
    assert timeline_relation(acknowledgement, same_exchange_ms) == "ambiguous"
    conflicting = trade(exchange_ms=1_001, received_ns=999_000_000)
    assert timeline_relation(acknowledgement, conflicting) == "ambiguous"
    assert apply_public_trade(QueueState.join_back(acknowledgement), conflicting).disposition == "timing_ambiguous"


def test_invalid_economic_values_fail_closed():
    with pytest.raises(ValueError, match="complementary"):
        trade(yes_price=Decimal("0.42"), no_price=Decimal("0.57"))
    with pytest.raises(ValueError, match="positive"):
        quote(quantity=Decimal("0"))
