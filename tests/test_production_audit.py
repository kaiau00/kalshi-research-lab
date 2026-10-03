import hashlib
import json
import sqlite3
from decimal import Decimal

from test_engine import prepared

from demo_execution.journal import Journal, dumps
from demo_execution.production_audit import compare_checkpoints, production_snapshot
from research_lab.checkpoint import encode
from research_lab.engine import Account, Replay
from research_lab.storage import canonical


def envelope(path, data):
    path.write_bytes(canonical({
        "data": data,
        "sha256": hashlib.sha256(canonical(data)).hexdigest(),
    }))


def forecast(threshold=80000):
    return {
        "expected_average": threshold + 10,
        "z": 1,
        "sigma_dollars": 10,
        "yes_probability": .8,
    }


def test_live_production_snapshot_is_read_only_and_reports_quote():
    replay, ticker, _, now = prepared(risk_per_market="3.00")
    before = replay.state.quality.copy()
    result = production_snapshot(replay.state, ticker, "yes", now, replay.cfg)
    assert result["available"]
    assert result["book"]["yes_ask"] == "0.40"
    assert result["selected_depth"] == "10"
    assert result["forecast"]["yes_probability"] > 0
    assert replay.state.quality == before


def test_journal_keeps_signal_and_arrival_production_snapshots(tmp_path):
    journal = Journal(tmp_path / "orders.sqlite3")
    assert journal.production_audit("client", "signal", {"available": True})
    assert not journal.production_audit("client", "signal", {"available": False})
    assert journal.production_audit("client", "arrival", {"available": False})
    summary = journal.production_audit_summary()
    assert summary["counts"] == {"arrival": 1, "signal": 1}
    assert {row["stage"] for row in summary["latest"]} == {"signal", "arrival"}
    journal.db.close()


def test_checkpoint_comparison_matches_same_side_and_time(tmp_path):
    ticker = "KXBTC15M-TEST"
    created_ns = 10_000_000_000
    order = {
        "ticker": ticker, "side": "yes", "created_ns": created_ns + 1_000_000_000,
        "limit": Decimal(".40"), "status": "filled", "probability": .8, "edge": .3,
        "fill_price": Decimal(".40"), "filled": 2, "forecast": forecast(),
    }
    closed = {**order, "pnl": Decimal("1.10")}
    pre = Replay()
    pre.accounts["adaptive_volatility"].orders = [order]
    pre.accounts["adaptive_volatility"].closed = [closed]
    pre_data = {"replay": encode(pre), "next_segment": 5, "last_digest": "a" * 64}
    envelope(tmp_path / "pre.json", pre_data)

    post = Replay()
    post.accounts = {"adaptive_baseline": Account("adaptive_baseline", Decimal("100"))}
    candidate_data = {
        "state": encode({"replay": post, "guard_quotes": {}}),
        "next_segment": 6, "last_digest": "b" * 64,
    }
    envelope(tmp_path / "candidate.json", candidate_data)

    journal = Journal(tmp_path / "demo.sqlite3")
    decision = {
        "ticker": ticker, "side": "yes", "created_ns": created_ns,
        "limit": Decimal(".42"), "quantity": 2, "forecast": forecast(),
    }
    exchange = {
        "fill_count_fp": "2.00", "taker_fill_cost_dollars": ".80",
        "taker_fees_dollars": ".05",
    }
    journal.db.execute("INSERT INTO intents VALUES (?,?,?,?,?,?,?,?)", (
        "client", ticker, created_ns, dumps({"count": "2"}), dumps(decision),
        "terminal", dumps(exchange), None,
    ))
    settlement = {"settled_time": "2026-01-01T00:15:00Z", "market_result": "yes"}
    journal.db.execute("INSERT INTO settlements VALUES (?,?,?)",
                       (ticker, dumps(settlement), "1.15"))
    journal.db.commit()
    journal.db.close()

    report = compare_checkpoints(
        tmp_path / "demo.sqlite3", tmp_path / "pre.json", tmp_path / "candidate.json")
    assert report["summary"]["demo_settled_fills"] == 1
    assert report["summary"]["same_side_production_fill_within_2_seconds"] == 1
    assert report["summary"]["production_replay_pnl_on_within_2_second_matches"] == "1.10"
    assert report["summary"]["maximum_effective_threshold_difference"] == 0


def test_checkpoint_checksum_failure_stops_audit(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"data": {}, "sha256": "bad"}))
    connection = sqlite3.connect(tmp_path / "demo.sqlite3")
    connection.executescript("""
        CREATE TABLE intents (ticker,created_ns,payload,decision,exchange_order);
        CREATE TABLE settlements (ticker,response,pnl);
    """)
    connection.close()
    try:
        compare_checkpoints(tmp_path / "demo.sqlite3", bad, bad)
    except ValueError as exc:
        assert "checksum" in str(exc).lower()
    else:
        raise AssertionError("corrupt checkpoint was accepted")
