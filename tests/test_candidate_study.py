import hashlib
import json
from decimal import Decimal

import pytest
from test_market import NS, START, warmed_state, ws

from candidate_study.engine import (
    CANDIDATES,
    CandidateEngine,
    blended_probability,
    calibrated_probability,
)
from candidate_study.runner import DATASET, SEED_DIGEST, START_SEGMENT, CandidateRunner
from research_lab.checkpoint import encode
from research_lab.demo import book_frame
from research_lab.engine import Replay
from research_lab.segments import catalog
from research_lab.storage import Store, canonical


def candidate_engine(quantity="10"):
    seed = Replay()
    seed.state, ticker = warmed_state()
    seed.state.apply(ws(book_frame(ticker, 1, ".40", ".38", quantity), START + 750))
    seed.last_ns = int((START + 750) * NS)
    return CandidateEngine.from_seed(seed), ticker


def test_seed_creates_fresh_independent_accounts():
    engine, _ = candidate_engine()
    assert tuple(engine.replay.accounts) == CANDIDATES
    assert all(account.cash == Decimal("100.00") and not account.orders
               for account in engine.replay.accounts.values())
    assert engine.replay.event_count == 0


def test_baseline_matches_registered_adaptive_decision():
    engine, ticker = candidate_engine()
    now = int((START + 750.1) * NS)
    engine._decide(engine.replay.accounts["adaptive_baseline"], ticker, now)

    reference = Replay()
    reference.state = engine.replay.state
    reference._decide(reference.accounts["adaptive_volatility"], ticker, now)
    actual = engine.replay.accounts["adaptive_baseline"].orders[0]
    expected = reference.accounts["adaptive_volatility"].orders[0]
    assert (actual["side"], actual["limit"], actual["quantity"]) == (
        expected["side"], expected["limit"], expected["quantity"])
    assert actual["probability"] == expected["probability"]
    assert actual["edge"] == expected["edge"]


def test_calibration_and_market_blend_shrink_extreme_probability():
    calibrated = calibrated_probability(0.9)
    blended = blended_probability(0.9, 0.5)
    assert 0.5 < calibrated < 0.9
    assert 0.5 < blended < 0.9
    assert calibrated_probability(0.1) == pytest.approx(1 - calibrated)


def test_guard_requires_two_consecutive_quotes_and_records_stress():
    engine, ticker = candidate_engine()
    engine.replay.state.forecast = lambda *args, **kwargs: {"yes_probability": 0.9, "z": 2}
    account = engine.replay.accounts["adaptive_calibrated_guarded"]
    first = int((START + 750.1) * NS)
    engine._decide(account, ticker, first)
    assert not account.orders
    assert account.rejected["guard_persistence"] == 1
    engine._decide(account, ticker, first + NS)
    assert len(account.orders) == 1
    assert account.orders[0]["stressed_edge"] >= engine.replay.cfg.min_edge
    assert account.orders[0]["quoted_binary_spread"] == Decimal("0.02")


def test_guard_rejects_insufficient_depth():
    engine, ticker = candidate_engine(quantity="1")
    engine.replay.state.forecast = lambda *args, **kwargs: {"yes_probability": 0.9, "z": 2}
    account = engine.replay.accounts["adaptive_calibrated_guarded"]
    engine._decide(account, ticker, int((START + 750.1) * NS))
    assert not account.orders
    assert account.rejected["guard_depth"] == 1


def test_runner_seeds_once_and_registration_mismatch_fails(tmp_path, monkeypatch):
    data = tmp_path
    (data / "segments-v6").mkdir()
    frozen = data / "comparisons" / "v6-002"
    frozen.mkdir(parents=True)
    seed = Replay()
    seed_data = {
        "dataset": DATASET, "next_segment": START_SEGMENT,
        "last_digest": SEED_DIGEST, "replay": encode(seed),
    }
    (frozen / "checkpoint.json").write_bytes(canonical({
        "data": seed_data, "sha256": hashlib.sha256(canonical(seed_data)).hexdigest(),
    }))
    monkeypatch.setenv("LAB_DATA_DIR", str(data))
    runner = CandidateRunner()
    try:
        assert runner.next_segment == START_SEGMENT
        assert tuple(runner.engine.replay.accounts) == CANDIDATES
        registration_path = data / "candidate-studies" / "003" / "registration.json"
        saved = json.loads(registration_path.read_text())
        saved["shared"]["min_edge"] = 0.05
        registration_path.write_bytes(canonical(saved))
    finally:
        runner.close()
    with pytest.raises(RuntimeError, match="registration/source mismatch"):
        CandidateRunner()


def test_runner_processes_verified_hot_segment_and_resumes(tmp_path, monkeypatch):
    segments = tmp_path / "segments-v6"
    segments.mkdir()
    frozen = tmp_path / "comparisons" / "v6-002"
    frozen.mkdir(parents=True)
    seed_data = {
        "dataset": DATASET, "next_segment": START_SEGMENT,
        "last_digest": SEED_DIGEST, "replay": encode(Replay()),
    }
    (frozen / "checkpoint.json").write_bytes(canonical({
        "data": seed_data, "sha256": hashlib.sha256(canonical(seed_data)).hexdigest(),
    }))
    path = segments / f"segment-{START_SEGMENT:08d}.sqlite3"
    store = Store(path)
    try:
        store.append("segment_start", {
            "dataset": DATASET, "segment": START_SEGMENT, "previous_digest": SEED_DIGEST,
        }, received_ns=1)
        store.commit()
        prefix = store.prefix()
    finally:
        store.close()
    cat = catalog(segments)
    try:
        cat.execute("INSERT OR REPLACE INTO settings VALUES('dataset',?)", (DATASET,))
        cat.execute("INSERT INTO segments(id,path,status,count,digest,previous_digest) VALUES(?,?,?,?,?,?)",
                    (START_SEGMENT, path.name, "sealed", prefix["last_event_id"],
                     prefix["sha256_chain"], SEED_DIGEST))
        cat.commit()
    finally:
        cat.close()
    monkeypatch.setenv("LAB_DATA_DIR", str(segments))
    runner = CandidateRunner()
    try:
        assert runner._process_next() == "complete"
        assert runner.next_segment == START_SEGMENT + 1
    finally:
        runner.close()
    resumed = CandidateRunner()
    try:
        assert resumed.next_segment == START_SEGMENT + 1
        assert resumed.engine.replay.event_count == 1
    finally:
        resumed.close()
