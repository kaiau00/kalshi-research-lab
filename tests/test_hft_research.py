import asyncio
import json

import pytest

from hft_research.contracts import (
    BaselineAction,
    JevDecision,
    QuotePolicy,
    Regime,
    apply_jev_veto,
)
from hft_research.forward_tape import (
    ForwardTapeRecorder,
    initial_registration,
    market_subscription,
    subscription_updates,
    summarize_tape,
)
from hft_research.registration import JEV_MODEL, registration, registration_hash
from hft_research.tape import parse_public_trade, trade_subscription


def decision(policy=QuotePolicy.BOTH, taker=True):
    return JevDecision(
        regime=Regime.CALM,
        quote_policy=policy,
        taker_allowed=taker,
        model_trust=0.8,
        adverse_selection_risk=0.2,
    )


def test_jev_can_remove_but_never_create_permissions():
    baseline = BaselineAction(quote_yes=True, quote_no=False, taker_allowed=False)
    assert apply_jev_veto(baseline, decision()) == baseline
    assert apply_jev_veto(baseline, decision(QuotePolicy.NO_ONLY, True)) == BaselineAction(
        quote_yes=False,
        quote_no=False,
        taker_allowed=False,
    )


def test_cancel_all_fails_closed():
    baseline = BaselineAction(quote_yes=True, quote_no=True, taker_allowed=True)
    actual = apply_jev_veto(baseline, decision(QuotePolicy.CANCEL_ALL, False))
    assert actual == BaselineAction(False, False, False)


def test_decision_probabilities_are_bounded():
    with pytest.raises(ValueError):
        JevDecision(Regime.CALM, QuotePolicy.BOTH, False, 1.01, 0.0)


def test_study_is_version_pinned_and_has_no_order_authority():
    study = registration()
    assert study["study"] == "028"
    assert study["jev"]["model"] == JEV_MODEL == "jev-1.13.0"
    assert study["jev"]["may_create_action"] is False
    assert study["scope"]["production_orders_authorized"] is False
    assert study["scope"]["demo_orders_authorized"] is False
    assert len(registration_hash()) == 64


def test_public_trade_contract_preserves_fixed_point_fields():
    ticker = "KXBTC15M-TEST"
    frame = {
        "type": "trade",
        "msg": {
            "trade_id": "one",
            "market_ticker": ticker,
            "yes_price_dollars": "0.3600",
            "no_price_dollars": "0.6400",
            "count_fp": "136.00",
            "taker_outcome_side": "no",
            "taker_book_side": "ask",
            "is_block_trade": False,
            "ts_ms": 1669149841000,
        },
    }
    trade = parse_public_trade(frame, {ticker})
    assert str(trade.count) == "136.00"
    assert trade.may_advance_public_queue is True
    assert trade_subscription({ticker}) == {"channels": ["trade"], "market_tickers": [ticker]}


def test_block_trade_never_proves_displayed_queue_consumption():
    ticker = "KXBTC15M-TEST"
    frame = {
        "type": "trade",
        "msg": {
            "trade_id": "block",
            "market_ticker": ticker,
            "yes_price_dollars": "0.5000",
            "no_price_dollars": "0.5000",
            "count_fp": "2.00",
            "taker_outcome_side": "yes",
            "taker_book_side": "bid",
            "is_block_trade": True,
            "ts_ms": 1,
        },
    }
    assert parse_public_trade(frame, {ticker}).may_advance_public_queue is False


def test_public_trade_contract_rejects_unsubscribed_or_incomplete_data():
    with pytest.raises(ValueError):
        trade_subscription(set())
    with pytest.raises(ValueError):
        parse_public_trade({"type": "trade", "msg": {}}, {"KXBTC15M-TEST"})


def trade_frame(ticker="KXBTC15M-TEST", trade_id="one", block=False):
    return {
        "type": "trade",
        "sid": 2,
        "seq": 1,
        "sending_ts_ms": 1669149841123,
        "msg": {
            "trade_id": trade_id,
            "market_ticker": ticker,
            "yes_price_dollars": "0.3600",
            "no_price_dollars": "0.6400",
            "count_fp": "136.00",
            "taker_outcome_side": "no",
            "taker_book_side": "ask",
            "is_block_trade": block,
            "ts_ms": 1669149841000,
        },
    }


def test_forward_tape_registration_and_subscription_are_isolated():
    kind, payload = initial_registration()
    assert kind == "hft_tape_registration"
    assert payload["production_orders_authorized"] is False
    assert payload["demo_orders_authorized"] is False
    assert market_subscription({"KXBTC15M-B", "KXBTC15M-A"}) == {
        "channels": ["orderbook_delta", "trade"],
        "market_tickers": ["KXBTC15M-A", "KXBTC15M-B"],
        "use_yes_price": True,
    }
    with pytest.raises(ValueError):
        market_subscription({"OTHER"})
    assert subscription_updates({9, 2}, {"KXBTC15M-B"}, "add_markets", 10) == [
        {
            "id": 11,
            "cmd": "update_subscription",
            "params": {
                "sid": 2,
                "market_tickers": ["KXBTC15M-B"],
                "action": "add_markets",
            },
        },
        {
            "id": 12,
            "cmd": "update_subscription",
            "params": {
                "sid": 9,
                "market_tickers": ["KXBTC15M-B"],
                "action": "add_markets",
            },
        },
    ]


def test_forward_tape_preserves_and_summarizes_trade(tmp_path, monkeypatch):
    monkeypatch.delenv("LAB_SEGMENTED", raising=False)
    path = tmp_path / "hft.sqlite3"
    recorder = ForwardTapeRecorder(path)
    ticker = "KXBTC15M-TEST"
    event = recorder.record_market_frame(trade_frame(ticker), "session", {ticker})
    recorder.store.commit()
    assert event.source_ns == 1669149841000 * 1_000_000
    assert recorder.status["trade_messages"] == 1
    assert recorder.status["non_block_trade_messages"] == 1
    recorder.store.close()
    asyncio.run(recorder.client.close())

    report = summarize_tape(path)
    assert report["integrity"]["verified_events"] == 2
    assert report["frame_types"] == {"trade": 1}
    assert report["unique_trade_ids"] == 1
    assert report["duplicate_trade_ids"] == 0
    assert report["zstd_archive_bytes"] > 0
    assert report["component_zstd_rates"]["trade"]["capture_bytes"] > 0
    json.dumps(report, allow_nan=False)
