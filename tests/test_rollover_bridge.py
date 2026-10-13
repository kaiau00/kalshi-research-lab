import hashlib
import json
import math
import shutil

from research_lab.checkpoint import encode
from research_lab.demo import book_frame, index_frame, market_fixture
from research_lab.engine import Replay
from research_lab.market import MarketState
from research_lab.segments import archive_writer, catalog
from research_lab.storage import Event, Store, canonical
from rollover_bridge import runner as rollover_runner
from rollover_bridge.analysis import development_report
from rollover_bridge.features import forecast
from rollover_bridge.runner import (
    DATASET,
    SEED_DIGEST,
    START_SEGMENT,
    LocalRolloverRunner,
    RolloverRunner,
)
from rollover_bridge.tape import DecisionTape

NS = 10**9
START = 1_800_000_000


def ws(frame, seconds, sequence_session="rollover-test"):
    return Event(1, int(seconds * NS), None, "ws", {
        "frame": frame, "session": sequence_session, "book_convention": "yes_price",
    })


def rollover_state(momentum=0.0):
    state = MarketState()
    market = market_fixture(START, "ROLLOVER")
    state.apply(Event(1, (START - 700) * NS, None, "market", {"market": market}))
    for second in range(START - 700, START + 6):
        price = 80_000 * math.exp(momentum * (second - START))
        state.apply(ws(index_frame(second, price), second + 0.01))
    return state, market


def test_rollover_forecast_uses_only_received_history_and_gap_direction():
    upward, market = rollover_state(momentum=0.00001)
    result = forecast(upward, market["ticker"], int((START + 5.1) * NS))
    assert result is not None
    assert result.rollover_gap_log > 0
    assert result.prior_minute_velocity > 0
    assert result.structural_yes_probability > 0.5
    frozen = result.to_dict()
    upward.apply(ws(index_frame(START + 6, 1), START + 6.01))
    assert result.to_dict() == frozen


def test_rollover_forecast_fails_closed_on_prior_history_gap():
    state, market = rollover_state()
    state.index = type(state.index)(
        (row for row in state.index if row[0] != START - 30), maxlen=7200)
    assert forecast(state, market["ticker"], int((START + 5.1) * NS)) is None


def test_decision_tape_captures_first_post_latency_quote_and_official_result():
    tape = DecisionTape()
    market = market_fixture(START, "TAPE")
    tape.feed(Event(1, (START - 700) * NS, None, "market", {"market": market}))
    sequence = 0
    for second in range(START - 700, START + 5):
        sequence += 1
        tape.feed(ws(index_frame(second, 80_000 + (second - START) * 0.1), second + 0.01))
    sequence += 1
    tape.feed(ws(book_frame(market["ticker"], sequence, ".52", ".50"), START + 5.02))
    row = tape.rows[(market["ticker"], 5)]
    assert row["decision_status"] == "usable"
    assert row["arrival_status"] == "pending"
    sequence += 1
    tape.feed(ws(book_frame(market["ticker"], sequence, ".53", ".51"), START + 5.60))
    row = tape.rows[(market["ticker"], 5)]
    assert row["arrival_status"] == "quoted"
    assert row["arrival_quote"]["yes_ask"] == "0.53"
    finalized = {**market, "status": "finalized", "result": "yes"}
    tape.feed(Event(1, (START + 901) * NS, None, "market", {"market": finalized}))
    assert row["result"] == "yes"


def test_decision_tape_records_missing_inputs_instead_of_inventing_a_row():
    tape = DecisionTape()
    market = market_fixture(START, "MISSING")
    tape.feed(Event(1, START * NS, None, "market", {"market": market}))
    tape.feed(ws(book_frame(market["ticker"], 1), START + 5.01))
    row = tape.rows[(market["ticker"], 5)]
    assert row["decision_status"] == "missing_forecast_inputs"
    assert "forecast" not in row


def test_decision_tape_rebuilds_pending_arrival_index_after_resume():
    tape = DecisionTape()
    market = market_fixture(START, "RESUME")
    tape.feed(Event(1, (START - 700) * NS, None, "market", {"market": market}))
    sequence = 0
    for second in range(START - 700, START + 5):
        sequence += 1
        tape.feed(ws(index_frame(second, 80_000), second + 0.01))
    sequence += 1
    tape.feed(ws(book_frame(market["ticker"], sequence, ".52", ".50"), START + 5.02))
    key = (market["ticker"], 5)
    assert tape.rows[key]["arrival_status"] == "pending"

    resumed = DecisionTape.from_snapshot(tape.snapshot())
    sequence += 1
    resumed.feed(ws(book_frame(market["ticker"], sequence, ".53", ".51"), START + 5.60))
    assert resumed.rows[key]["arrival_status"] == "quoted"
    assert resumed.rows[key]["arrival_quote"]["yes_ask"] == "0.53"


def test_runner_is_registered_resumable_and_verifies_segment_linkage(tmp_path, monkeypatch):
    segment_root = tmp_path / "segments-v6"
    segment_root.mkdir()
    seed_root = tmp_path / "comparisons" / "v6-002"
    seed_root.mkdir(parents=True)
    seed = Replay()
    seed_data = {
        "dataset": DATASET,
        "next_segment": START_SEGMENT,
        "last_digest": SEED_DIGEST,
        "replay": encode(seed),
    }
    (seed_root / "checkpoint.json").write_bytes(canonical({
        "data": seed_data,
        "sha256": hashlib.sha256(canonical(seed_data)).hexdigest(),
    }))
    path = segment_root / f"segment-{START_SEGMENT:08d}.sqlite3"
    store = Store(path)
    try:
        store.append("segment_start", {
            "dataset": DATASET,
            "segment": START_SEGMENT,
            "previous_digest": SEED_DIGEST,
        }, received_ns=1)
        store.commit()
        stats = store.stats()
    finally:
        store.close()
    cat = catalog(segment_root)
    try:
        cat.execute("INSERT OR REPLACE INTO settings VALUES('dataset',?)", (DATASET,))
        cat.execute(
            "INSERT INTO segments(id,path,status,count,digest,previous_digest,stats) "
            "VALUES(?,?,?,?,?,?,?)",
            (START_SEGMENT, path.name, "sealed", stats["prefix"]["last_event_id"],
             stats["prefix"]["sha256_chain"], SEED_DIGEST, json.dumps(stats)),
        )
        cat.commit()
    finally:
        cat.close()
    monkeypatch.setenv("LAB_DATA_DIR", str(tmp_path))
    runner = RolloverRunner()
    try:
        assert runner.next_segment == START_SEGMENT
        assert runner.process_next() == "processed"
        assert runner.next_segment == START_SEGMENT + 1
    finally:
        runner.close()
    resumed = RolloverRunner()
    try:
        assert resumed.next_segment == START_SEGMENT + 1
        assert resumed.tape.events == 1
    finally:
        resumed.close()


def test_local_runner_downloads_resumes_and_removes_temporary_archives(tmp_path, monkeypatch):
    dataset = "local-test-dataset"
    start_segment = 10
    seed_digest = "1" * 64
    source_archives = tmp_path / "source"
    source_archives.mkdir()
    rows = []
    previous_digest = seed_digest
    for segment in (10, 11):
        payload = {"dataset": dataset, "segment": segment, "previous_digest": previous_digest}
        received_ns = segment * NS
        digest = hashlib.sha256(
            bytes.fromhex("0" * 64)
            + canonical([received_ns, None, "segment_start", payload])
        ).hexdigest()
        archive = source_archives / f"segment-{segment}.zst"
        with archive_writer(archive) as stream:
            stream.write(canonical([1, received_ns, None, "segment_start", payload]) + b"\n")
        archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        rows.append({
            "id": segment,
            "status": "archived",
            "count": 1,
            "digest": digest,
            "previous_digest": previous_digest,
            "archive_key": f"segment-{segment}.zst",
            "archive_sha": archive_sha,
        })
        previous_digest = digest

    monkeypatch.setattr(rollover_runner, "DATASET", dataset)
    monkeypatch.setattr(rollover_runner, "START_SEGMENT", start_segment)
    monkeypatch.setattr(rollover_runner, "SEED_DIGEST", seed_digest)
    monkeypatch.setattr(rollover_runner, "TERMINAL_SEGMENT", 11)
    monkeypatch.setattr(rollover_runner, "TERMINAL_DIGEST", rows[-1]["digest"])
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(canonical(rows))

    seed = Replay()
    seed_data = {
        "dataset": dataset,
        "next_segment": start_segment,
        "last_digest": seed_digest,
        "replay": encode(seed),
    }
    seed_path = tmp_path / "seed.json"
    seed_path.write_bytes(canonical({
        "data": seed_data,
        "sha256": hashlib.sha256(canonical(seed_data)).hexdigest(),
    }))

    class FakeBucket:
        def get(self, key, destination, expected):
            source = source_archives / key
            assert hashlib.sha256(source.read_bytes()).hexdigest() == expected
            shutil.copyfile(source, destination)

    root = tmp_path / "local-run"
    runner = LocalRolloverRunner(manifest, seed_path, root, checkpoint_every=10, bucket=FakeBucket())
    try:
        assert runner.process_next() == "processed"
        assert runner.next_segment == 11
        assert not any((root / "archives").iterdir())
    finally:
        runner.close()

    resumed = LocalRolloverRunner(manifest, seed_path, root, checkpoint_every=1, bucket=FakeBucket())
    try:
        assert resumed.next_segment == 11
        assert resumed.process_next() == "processed"
        assert resumed.process_next() == "development_complete"
        assert json.loads((root / "development-report.json").read_text())["development_complete"]
    finally:
        resumed.close()


def synthetic_analysis_rows():
    rows = []
    for day in range(10):
        for market_index in range(10):
            positive = market_index % 2 == 0
            decision_ns = (START + day * 86400 + market_index * 900) * NS
            gap = 0.003 if positive else -0.003
            result = "yes" if positive else "no"
            ticker = f"KXBTC15M-D{day:02d}-M{market_index:02d}"
            rows.append({
                "ticker": ticker,
                "sample_offset_seconds": 5,
                "decision_ns": decision_ns,
                "finalized_received_ns": decision_ns + 901 * NS,
                "decision_status": "usable",
                "arrival_status": "quoted",
                "result": result,
                "decision_quote": {"yes_midpoint": 0.5},
                "arrival_quote": {
                    "yes_ask": "0.51", "no_ask": "0.51",
                    "yes_depth": "10", "no_depth": "10",
                },
                "forecast": {
                    "continuous_variance_per_second": 1e-8,
                    "jump_variance_per_second": 0.0,
                    "seconds_left": 895,
                    "rollover_gap_log": gap,
                    "prior_minute_velocity": gap / 60,
                    "posterior_velocity": gap / 30,
                    "jump_share": 0.0,
                    "structural_yes_probability": 0.9 if positive else 0.1,
                },
            })
    return rows


def test_development_analysis_fits_only_earlier_dates_and_one_trade_per_market():
    report = development_report(synthetic_analysis_rows())
    assert len(report["training_dates"]) == 6
    assert len(report["evaluation_dates"]) == 4
    assert report["probability_comparison"]["rollover_log_loss"] < 0.2
    assert report["probability_comparison"]["market_log_loss"] > 0.69
    assert (report["probability_comparison"]["rollover_brier_score"]
            < report["probability_comparison"]["market_brier_score"])
    assert report["results"]["settled_trades"] == 40
    assert report["results"]["wins"] == 40
    assert report["results"]["realized_net_pnl"] > 0
