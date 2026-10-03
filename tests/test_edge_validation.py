import hashlib
import json
from decimal import Decimal

from candidate_study.engine import CANDIDATES
from edge_validation.report import EdgeValidationReporter, build_report
from research_lab.checkpoint import encode
from research_lab.engine import Account, Replay, entry_fee
from research_lab.storage import canonical


def populated_replay(days=20, trades_per_day=5):
    replay = Replay()
    replay.accounts = {name: Account(name, Decimal("100")) for name in CANDIDATES}
    for name, account in replay.accounts.items():
        probability = .55 if name == "adaptive_baseline" else .80
        running = Decimal("100")
        for day in range(days):
            for index in range(trades_per_day):
                price, count = Decimal(".40"), 1
                fee = entry_fee(price, count, replay.cfg)
                cost = price + fee
                pnl = Decimal(1) - cost
                running += pnl
                account.closed.append({
                    "ticker": f"KXBTC15M-{day:02d}-{index}-{name}",
                    "settled_day": f"2026-10-{day + 1:02d}", "settled_ns": day * 100 + index,
                    "pnl": pnl, "probability": probability, "won": True,
                    "fill_price": price, "filled": count, "payout": Decimal(1),
                    "cost": cost, "fees": fee,
                })
                account.orders.append({"status": "filled"})
                account.equity.append({"cost_equity": float(running)})
        account.cash = running
    return replay


def test_edge_report_calculates_every_gate_without_selecting_a_winner():
    report = build_report(populated_replay(), {"candidate_study": "003"})
    calibrated = report["accounts"]["adaptive_calibrated"]
    baseline = report["accounts"]["adaptive_baseline"]
    assert report["state"] == "candidate_passed_screen"
    assert calibrated["settled_markets"] == 100
    assert calibrated["pnl_without_top_three_winners"] > 0
    assert calibrated["stressed_pnl"]["2"] > 0
    assert calibrated["uncertainty"]["available"]
    assert calibrated["promotion_screen_passed"]
    assert not baseline["gates"]["better_log_loss_than_baseline"]
    assert report["selection"]["automatic_winner"] is None


def test_edge_report_stays_collecting_below_preregistered_sample():
    report = build_report(populated_replay(days=4, trades_per_day=2), {"candidate_study": "003"})
    assert report["state"] == "collecting"
    assert not report["minimum_sample_ready"]
    assert not report["accounts"]["adaptive_calibrated"]["uncertainty"]["available"]
    assert not report["selection"]["eligible"]


def test_reporter_verifies_candidate_checkpoint_and_persists_report(tmp_path):
    root = tmp_path / "candidate-studies" / "003"
    root.mkdir(parents=True)
    registration = {"source_sha256": "candidate-source"}
    (root / "registration.json").write_bytes(canonical(registration))
    state = {"replay": populated_replay(days=4, trades_per_day=2), "guard_quotes": {}}
    data = {
        "study": "003", "registration_sha256": hashlib.sha256(canonical(registration)).hexdigest(),
        "dataset": "dataset", "next_segment": 10, "last_digest": "a" * 64,
        "state": encode(state),
    }
    (root / "checkpoint.json").write_bytes(canonical({
        "data": data, "sha256": hashlib.sha256(canonical(data)).hexdigest(),
    }))
    reporter = EdgeValidationReporter(root)
    report = reporter.refresh()
    assert report["state"] == "collecting"
    assert report["manifest"]["next_segment"] == 10
    saved = json.loads((tmp_path / "edge-validation" / "001" / "latest-report.json").read_text())
    assert saved["report_sha256"] == report["report_sha256"]

    envelope = json.loads((root / "checkpoint.json").read_text())
    envelope["sha256"] = "bad"
    (root / "checkpoint.json").write_bytes(canonical(envelope))
    assert reporter.refresh()["state"] == "stopped_error"
