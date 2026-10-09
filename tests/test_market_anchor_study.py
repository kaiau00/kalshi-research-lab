import hashlib
import json
from decimal import Decimal

from market_anchor_study.report import (
    PROSPECTIVE_START_NS,
    SOURCE_DATASET,
    SOURCE_REGISTRATION_SHA256,
    checkpoint_report,
    prospective_status,
    qualifies,
    registration,
    summarize,
)
from research_lab.checkpoint import encode
from research_lab.engine import Account, Replay
from research_lab.storage import canonical


def trade(**changes):
    row = {
        "ticker": "KXBTC15M-26OCT091200-00",
        "created_ns": 10,
        "settled_ns": 20,
        "settled_day": "2026-10-09",
        "side": "yes",
        "won": True,
        "payout": Decimal("2"),
        "pnl": Decimal("1.18"),
        "limit": Decimal("0.40"),
        "fill_price": Decimal("0.40"),
        "filled": 2,
        "forecast": {"yes_probability": 0.56},
        "market_yes_probability": 0.50,
        "quoted_binary_spread": Decimal("0.02"),
    }
    row.update(changes)
    return row


def test_filter_uses_decision_quote_and_market_agreement_boundaries():
    assert qualifies(trade(limit=Decimal("0.30")))
    assert not qualifies(trade(limit=Decimal("0.95")))
    assert qualifies(trade(forecast={"yes_probability": 0.58}))
    assert not qualifies(trade(forecast={"yes_probability": 0.581}))
    assert not qualifies(trade(quoted_binary_spread=Decimal("0.021")))
    assert qualifies(trade(limit=Decimal("0.40"), fill_price=Decimal("0.99")))


def test_summary_reports_concentration_stress_and_incomplete_date_gate():
    rows = [trade(ticker=f"KXBTC15M-26OCT0912{i:02d}-00", created_ns=i, settled_ns=100 + i)
            for i in range(4)]
    result = summarize(rows, observed_dates=["2026-10-09"])
    assert result["settled_markets"] == 4
    assert result["realized_net_pnl"] == 4.72
    assert result["pnl_without_top_three_winners"] == 1.18
    assert result["stressed_pnl"]["2"] < result["realized_net_pnl"]
    assert not result["gates"]["minimum_20_utc_dates"]
    assert not result["promotion_screen_passed"]


def test_checkpoint_report_verifies_envelope_and_filters_baseline(tmp_path):
    replay = Replay()
    account = Account("adaptive_baseline", Decimal("100"))
    account.closed = [
        trade(),
        trade(
            ticker="KXBTC15M-26OCT101215-15",
            limit=Decimal("0.10"),
            settled_day="2026-10-10",
        ),
    ]
    replay.accounts = {"adaptive_baseline": account}
    data = {"dataset": "dataset", "next_segment": 3, "last_digest": "abc",
            "state": encode({"replay": replay})}
    path = tmp_path / "checkpoint.json"
    path.write_bytes(canonical({"data": data, "sha256": hashlib.sha256(canonical(data)).hexdigest()}))
    report = checkpoint_report(path, "adaptive_baseline", phase="secondary")
    assert report["results"]["settled_markets"] == 1
    assert report["results"]["observed_utc_dates"] == 2
    assert report["registration"] == registration()
    assert report["production_orders_authorized"] is False
    envelope = json.loads(path.read_text())
    envelope["data"]["next_segment"] = 4
    path.write_text(json.dumps(envelope))
    try:
        checkpoint_report(path, "adaptive_baseline")
    except ValueError as exc:
        assert "checksum" in str(exc)
    else:
        raise AssertionError("tampered checkpoint was accepted")


def test_prospective_status_excludes_pre_registration_trades(tmp_path):
    candidate = tmp_path / "candidate-studies" / "003"
    candidate.mkdir(parents=True)
    replay = Replay()
    account = Account("adaptive_baseline", Decimal("100"))
    account.closed = [
        trade(created_ns=PROSPECTIVE_START_NS - 1),
        trade(
            ticker="KXBTC15M-26OCT101215-15",
            created_ns=PROSPECTIVE_START_NS,
            settled_day="2026-10-10",
        ),
    ]
    replay.accounts = {"adaptive_baseline": account}
    data = {
        "dataset": SOURCE_DATASET,
        "registration_sha256": SOURCE_REGISTRATION_SHA256,
        "next_segment": 4,
        "last_digest": "def",
        "state": encode({"replay": replay}),
    }
    (candidate / "checkpoint.json").write_bytes(canonical({
        "data": data,
        "sha256": hashlib.sha256(canonical(data)).hexdigest(),
    }))
    report = prospective_status(tmp_path, now_ns=PROSPECTIVE_START_NS)
    assert report["state"] == "collecting"
    assert report["results"]["settled_markets"] == 1
    assert report["source"]["created_after_ns"] == PROSPECTIVE_START_NS
    assert report["production_orders_authorized"] is False
