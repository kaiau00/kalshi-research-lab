import hashlib
from datetime import datetime
from decimal import Decimal

from conservative_anchor.report import (
    PROSPECTIVE_START_NS,
    SOURCE_DATASET,
    SOURCE_REGISTRATION_SHA256,
    prospective_status,
    select,
)
from conservative_anchor.rules import performance_guard, qualifies
from research_lab.checkpoint import encode
from research_lab.engine import Account, Replay
from research_lab.storage import canonical


def ns(iso):
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1e9)


def trade(**changes):
    row = {
        "ticker": "KXBTC15M-26OCT101815-15",
        "created_ns": PROSPECTIVE_START_NS,
        "fill_ns": PROSPECTIVE_START_NS + 500_000_000,
        "settled_ns": PROSPECTIVE_START_NS + 300_000_000_000,
        "settled_day": "2026-10-10",
        "side": "yes",
        "won": True,
        "payout": Decimal("2"),
        "pnl": Decimal("1.18"),
        "limit": Decimal("0.40"),
        "fill_price": Decimal("0.40"),
        "filled": 2,
        "forecast": {"yes_probability": 0.559},
        "market_yes_probability": 0.50,
        "quoted_binary_spread": Decimal("0.01"),
    }
    row.update(changes)
    return row


def test_conservative_filter_has_frozen_price_gap_spread_and_stress_boundaries():
    assert qualifies(trade())
    assert not qualifies(trade(limit=Decimal("0.85")))
    assert not qualifies(trade(quoted_binary_spread=Decimal("0.011")))
    assert not qualifies(trade(forecast={"yes_probability": 0.561}))
    assert not qualifies(trade(limit=Decimal("0.54"), forecast={"yes_probability": 0.559}))


def test_performance_guard_halts_daily_and_total_losses():
    rows = [
        {"ticker": "a", "settled_ns": ns("2026-10-10T12:00:00Z"),
         "settled_day": "2026-10-10", "pnl": "-0.75"},
        {"ticker": "b", "settled_ns": ns("2026-10-10T12:15:00Z"),
         "settled_day": "2026-10-10", "pnl": "-0.75"},
        {"ticker": "c", "settled_ns": ns("2026-10-10T12:30:00Z"),
         "settled_day": "2026-10-10", "pnl": "-0.75"},
    ]
    guard = performance_guard(rows, ns("2026-10-10T13:00:00Z"))
    assert guard["reason"] == "daily_loss_limit"
    assert guard["daily_consecutive_losses"] == 3
    drawdown = performance_guard([
        {"ticker": str(i), "settled_ns": ns("2026-10-09T12:00:00Z") + i,
         "settled_day": "2026-10-09", "pnl": "-1.00"}
        for i in range(5)
    ], ns("2026-10-10T13:00:00Z"))
    assert drawdown["reason"] == "maximum_realized_drawdown"


def test_selection_enforces_one_hour_between_fills():
    rows = [
        trade(ticker="a"),
        trade(ticker="b", created_ns=PROSPECTIVE_START_NS + 3_599_000_000_000,
              fill_ns=PROSPECTIVE_START_NS + 3_599_500_000_000),
        trade(ticker="c", created_ns=PROSPECTIVE_START_NS + 3_601_000_000_000,
              fill_ns=PROSPECTIVE_START_NS + 3_601_500_000_000),
    ]
    assert [row["ticker"] for row in select(rows)] == ["a", "c"]


def test_prospective_report_uses_frozen_future_cutoff(tmp_path):
    candidate = tmp_path / "candidate-studies" / "003"
    candidate.mkdir(parents=True)
    replay = Replay()
    account = Account("adaptive_baseline", Decimal("100"))
    account.closed = [trade(created_ns=PROSPECTIVE_START_NS - 1), trade()]
    replay.accounts = {"adaptive_baseline": account}
    data = {
        "dataset": SOURCE_DATASET,
        "registration_sha256": SOURCE_REGISTRATION_SHA256,
        "next_segment": 10,
        "state": encode({"replay": replay}),
    }
    (candidate / "checkpoint.json").write_bytes(canonical({
        "data": data,
        "sha256": hashlib.sha256(canonical(data)).hexdigest(),
    }))
    report = prospective_status(tmp_path, now_ns=PROSPECTIVE_START_NS)
    assert report["state"] == "collecting"
    assert report["results"]["settled_markets"] == 1
    assert report["production_orders_authorized"] is False
