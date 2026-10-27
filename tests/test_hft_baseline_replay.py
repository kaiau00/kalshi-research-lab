from decimal import Decimal

from hft_research.baseline_replay import BaselineReplay, merge_events
from hft_research.queue import QueueState, QuoteAcknowledgement
from hft_research.tape import parse_public_trade
from research_lab.storage import Event


def test_merge_events_preserves_receipt_order():
    left = [Event(1, 10, None, "a", {}), Event(2, 30, None, "a", {})]
    right = [Event(1, 20, None, "b", {})]
    assert [(e.received_ns, e.kind) for e in merge_events(left, right)] == [
        (10, "a"),
        (20, "b"),
        (30, "a"),
    ]


def test_public_trade_fills_only_after_displayed_queue():
    replay = BaselineReplay()
    acknowledgement = QuoteAcknowledgement(
        "KXBTC15M-TEST", "yes", Decimal(".42"), Decimal(1), Decimal(2), 1_000, 1_000_000_000
    )
    from hft_research.baseline_replay import SimQuote

    replay.quotes[("KXBTC15M-TEST", "yes")] = SimQuote(
        "yes", Decimal(".42"), 1_000_000_000, 10_000_000_000, QueueState.join_back(acknowledgement)
    )
    frame = {
        "type": "trade",
        "msg": {
            "trade_id": "trade-1",
            "market_ticker": "KXBTC15M-TEST",
            "yes_price_dollars": ".42",
            "no_price_dollars": ".58",
            "count_fp": "2",
            "taker_outcome_side": "no",
            "taker_book_side": "ask",
            "is_block_trade": False,
            "ts_ms": 1001,
        },
    }
    parse_public_trade(frame, {"KXBTC15M-TEST"})
    replay.apply_trade(Event(1, 1_001_000_000, None, "ws", {"frame": frame}))
    assert replay.metrics["plausible_fills"] == 0
    frame["msg"].update(trade_id="trade-2", count_fp="1", ts_ms=1002)
    replay.apply_trade(Event(2, 1_002_000_000, None, "ws", {"frame": frame}))
    assert replay.metrics["plausible_fills"] == 1
    assert replay.inventory["KXBTC15M-TEST"] == 1


def test_credible_edge_requires_every_frozen_gate():
    replay = BaselineReplay()
    replay.dates = {f"2026-10-{day:02d}" for day in range(1, 21)}
    replay.first_ns = 1
    replay.last_ns = 2
    replay.metrics["plausible_fills"] = 1000
    replay.plausible_filled_contracts = Decimal("1000")
    replay.market_pnl = {f"m{i}": Decimal("1") for i in range(5)}
    report = replay.report()
    assert report["credible_edge"] is False  # one-cent stress erases this small sample
    assert report["jev_comparison_authorized"] is False


def test_fractional_public_trade_keeps_residual_quote_and_tracks_exact_exposure():
    replay = BaselineReplay()
    acknowledgement = QuoteAcknowledgement(
        "KXBTC15M-TEST", "yes", Decimal(".42"), Decimal(1), Decimal(0), 1_000, 1_000_000_000
    )
    from hft_research.baseline_replay import SimQuote

    replay.quotes[("KXBTC15M-TEST", "yes")] = SimQuote(
        "yes", Decimal(".42"), 1_000_000_000, 10_000_000_000, QueueState.join_back(acknowledgement)
    )
    frame = {
        "type": "trade",
        "msg": {
            "trade_id": "partial-1", "market_ticker": "KXBTC15M-TEST",
            "yes_price_dollars": ".42", "no_price_dollars": ".58", "count_fp": ".10",
            "taker_outcome_side": "no", "taker_book_side": "ask", "is_block_trade": False,
            "ts_ms": 1001,
        },
    }
    replay.apply_trade(Event(1, 1_001_000_000, None, "ws", {"frame": frame}))
    assert replay.inventory["KXBTC15M-TEST"] == Decimal(".10")
    assert replay.fills["KXBTC15M-TEST"]["yes"] == Decimal(".10")
    assert replay.plausible_filled_contracts == Decimal(".10")
    assert ("KXBTC15M-TEST", "yes") in replay.quotes


def test_trade_sidecar_control_message_does_not_affect_book_sequence():
    replay = BaselineReplay()
    sidecar_ok = Event(
        1,
        1_000_000_000,
        None,
        "ws",
        {"session": "separate-trade-feed", "frame": {"type": "ok", "sid": 1, "seq": 99}},
    )
    replay.consume([sidecar_ok])
    assert replay.state.seq == {}


def test_unquoted_public_trade_is_counted_without_parsing_or_evaluating():
    replay = BaselineReplay()
    trades = [
        Event(
            1,
            1_000_000_000,
            None,
            "ws",
            {"frame": {"type": "trade", "msg": {"market_ticker": "KXBTC15M-TEST"}}},
        ),
        Event(
            2,
            86_401_000_000_000,
            None,
            "ws",
            {"frame": {"type": "trade", "msg": {"market_ticker": "KXBTC15M-TEST"}}},
        ),
    ]
    report = replay.consume(trades)
    assert report["metrics"]["public_trades"] == 2
    assert "public_trades_considered" not in report["metrics"]
    assert report["rejections"] == {}
    assert report["dates"] == ["1970-01-01", "1970-01-02"]
