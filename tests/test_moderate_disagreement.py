import hashlib
from datetime import datetime
from decimal import Decimal

from moderate_disagreement.report import (
    PROSPECTIVE_START_NS,
    SOURCE_DATASET,
    SOURCE_REGISTRATION_SHA256,
    prospective_status,
    select,
    summarize,
)
from moderate_disagreement.rules import qualifies
from research_lab.checkpoint import encode
from research_lab.engine import Account, Replay
from research_lab.storage import canonical


def ns(iso):
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1e9)


def trade(**changes):
    row = {
        "ticker": "KXBTC15M-26OCT132200-00",
        "created_ns": PROSPECTIVE_START_NS,
        "fill_ns": PROSPECTIVE_START_NS + 500_000_000,
        "settled_ns": PROSPECTIVE_START_NS + 900_000_000_000,
        "settled_day": "2026-10-13",
        "side": "yes",
        "won": True,
        "result": "yes",
        "payout": Decimal("2"),
        "pnl": Decimal("1.1826"),
        "fees": Decimal("0.0174"),
        "limit": Decimal("0.40"),
        "fill_price": Decimal("0.40"),
        "filled": 2,
        "forecast": {"yes_probability": 0.48},
        "market_yes_probability": 0.41,
        "quoted_binary_spread": Decimal("0.01"),
    }
    row.update(changes)
    return row


def test_frozen_filter_boundaries_and_stressed_edge():
    assert qualifies(trade())
    assert not qualifies(trade(limit=Decimal("0.50")))
    assert not qualifies(trade(quoted_binary_spread=Decimal("0.011")))
    assert not qualifies(trade(forecast={"yes_probability": 0.47}))
    assert qualifies(trade(forecast={"yes_probability": 0.49}))
    assert not qualifies(trade(forecast={"yes_probability": 0.491}))
    assert not qualifies(trade(limit=Decimal("0.46")))


def test_selection_preserves_one_hour_cooldown():
    rows = [
        trade(ticker="a"),
        trade(ticker="b", created_ns=PROSPECTIVE_START_NS + 3_599_000_000_000),
        trade(ticker="c", created_ns=PROSPECTIVE_START_NS + 3_601_000_000_000),
    ]
    assert [row["ticker"] for row in select(rows)] == ["a", "c"]


def test_summary_reports_raw_and_market_calibration_without_authorizing_review():
    report = summarize([trade()], observed_dates=["2026-10-13"])
    assert report["settled_markets"] == 1
    assert set(report["calibration"]) == {"raw_model", "kalshi_midpoint"}
    assert report["gates"]["minimum_50_settlements"] is False
    assert report["review_gate_passed"] is False
    assert report["unresolved_exposure"] == 0


def test_prospective_status_excludes_pre_registration_trades(tmp_path):
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
    (candidate / "checkpoint.json").write_bytes(
        canonical({"data": data, "sha256": hashlib.sha256(canonical(data)).hexdigest()})
    )
    report = prospective_status(tmp_path, now_ns=PROSPECTIVE_START_NS)
    assert report["state"] == "collecting"
    assert report["results"]["settled_markets"] == 1
    assert report["production_orders_authorized"] is False
