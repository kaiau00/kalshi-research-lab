import pytest
from test_market import NS, START, warmed_state, ws

from research_lab.demo import book_frame, create_demo
from research_lab.engine import Replay
from research_lab.segments import catalog
from research_lab.storage import Store
from walk_forward_study import runner as runner_module
from walk_forward_study.engine import CONFIG_BY_NAME, CONFIGS, WalkForwardEngine, model_probability


def prepared_engine(quantity="10"):
    engine = WalkForwardEngine()
    engine.replay.state, ticker = warmed_state()
    engine.replay.state.apply(ws(book_frame(ticker, 1, ".40", ".38", quantity), START + 750))
    engine.active.add(ticker)
    return engine, ticker


def test_fixed_grid_has_exactly_40_unique_staged_configurations():
    assert len(CONFIGS) == len({row["name"] for row in CONFIGS}) == 40
    assert CONFIG_BY_NAME["signal_raw_e04"] == {
        "name": "signal_raw_e04", "model": "raw", "min_edge": 0.04,
        "min_seconds": 5, "max_seconds": 300, "max_spread": None, "persistence": 1,
    }


def test_probability_models_are_symmetric_and_market_blends_move_toward_market():
    calibrated = model_probability("calibrated", 0.9, 0.5)
    assert 0.5 < calibrated < 0.9
    assert model_probability("calibrated", 0.1, 0.5) == pytest.approx(1 - calibrated)
    assert 0.5 < model_probability("blend25", 0.9, 0.5) < 0.9
    assert model_probability("blend75", 0.9, 0.5) < model_probability("blend25", 0.9, 0.5)


def test_raw_four_percent_configuration_matches_original_adaptive_decision():
    engine, ticker = prepared_engine()
    now = int((START + 750.1) * NS)
    opportunity = engine._opportunity(ticker, now)
    engine._evaluate(ticker, now, opportunity)
    actual = engine.replay.accounts["signal_raw_e04"].orders[0]

    reference = Replay()
    reference.state = engine.replay.state
    reference._decide(reference.accounts["adaptive_volatility"], ticker, now)
    expected = reference.accounts["adaptive_volatility"].orders[0]
    assert (actual["side"], actual["limit"], actual["quantity"]) == (
        expected["side"], expected["limit"], expected["quantity"])
    assert actual["probability"] == expected["probability"]
    assert actual["edge"] == expected["edge"]


def test_persistence_configuration_requires_two_consecutive_seconds():
    engine, ticker = prepared_engine()
    engine.replay.state.forecast = lambda *args, **kwargs: {"yes_probability": 0.9, "z": 2}
    name = "persist_calibrated_e06_30_180_s07"
    account = engine.replay.accounts[name]
    first = int((START + 750.1) * NS)
    opportunity = engine._opportunity(ticker, first)
    engine._evaluate(ticker, first, opportunity)
    assert not account.orders
    assert account.rejected["persistence_filter"] == 1
    engine._evaluate(ticker, first + NS, opportunity)
    assert len(account.orders) == 1
    assert name in engine.pending_accounts


def test_canceled_orders_are_compacted_but_counted(tmp_path):
    engine, ticker = prepared_engine()
    now = int((START + 750.1) * NS)
    engine._evaluate(ticker, now, engine._opportunity(ticker, now))
    account = engine.replay.accounts["signal_raw_e04"]
    account.orders[0]["status"] = "canceled_limit_not_marketable"
    account.pending.clear()
    engine._compact(account)
    assert account.study_stats["submitted"] == 1
    assert not account.orders


def test_end_to_end_synthetic_replay_produces_bounded_results(tmp_path):
    path = tmp_path / "demo.sqlite3"
    create_demo(path, markets=1)
    store = Store(path, readonly=True)
    engine = WalkForwardEngine()
    try:
        for event in store.events():
            engine.feed(event)
    finally:
        store.close()
    result = engine.results()
    assert result["synthetic"] is True
    assert len(result["accounts"]) == 40
    assert result["selection"]["development_only"] is True
    assert all(not row["promotion_eligible"] for row in result["accounts"].values())


def test_runner_processes_initial_verified_segment_and_resumes(tmp_path, monkeypatch):
    segments = tmp_path / "segments-v6"
    segments.mkdir()
    path = segments / "segment-00000000.sqlite3"
    store = Store(path)
    try:
        store.append("experiment_registration", {"config": {}, "source_sha256": "recorded"}, received_ns=1)
        store.commit()
        prefix = store.prefix()
    finally:
        store.close()
    cat = catalog(segments)
    try:
        cat.execute("INSERT OR REPLACE INTO settings VALUES('dataset',?)", (runner_module.DATASET,))
        cat.execute("INSERT INTO segments(id,path,status,count,digest,previous_digest) VALUES(?,?,?,?,?,?)",
                    (0, path.name, "sealed", prefix["last_event_id"],
                     prefix["sha256_chain"], "0" * 64))
        cat.commit()
    finally:
        cat.close()
    monkeypatch.setenv("LAB_DATA_DIR", str(segments))
    monkeypatch.setattr(runner_module, "END_SEGMENT", 0)
    monkeypatch.setattr(runner_module, "TERMINAL_DIGEST", prefix["sha256_chain"])
    monkeypatch.setattr(runner_module, "CHECKPOINT_INTERVAL", 1)
    runner = runner_module.ParameterRunner()
    try:
        assert runner._process_next() == "finished"
        assert runner.next_segment == 1
        assert runner.engine.replay.event_count == 1
    finally:
        runner.close()
    resumed = runner_module.ParameterRunner()
    try:
        assert resumed.next_segment == 1
        assert resumed.registration["terminal_digest"] == prefix["sha256_chain"]
    finally:
        resumed.close()
