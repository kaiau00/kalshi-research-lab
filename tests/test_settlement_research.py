import hashlib
import json
import math
import shutil
from datetime import datetime, timezone

from research_lab.checkpoint import encode
from research_lab.demo import book_frame, index_frame, market_fixture
from research_lab.engine import Replay
from research_lab.market import MarketState
from research_lab.segments import archive_writer
from research_lab.storage import Event, canonical
from settlement_research import market_calibration
from settlement_research import runner as settlement_runner
from settlement_research.features import realized_features
from settlement_research.market_calibration import development_report, fit_beta, predict_beta
from settlement_research.runner import LocalSettlementResearchRunner
from settlement_research.tape import DecisionTape

NS = 10**9
START = 1_800_000_000


def ws(frame, seconds, session="settlement-test"):
    return Event(1, int(seconds * NS), None, "ws", {
        "frame": frame,
        "session": session,
        "book_convention": "yes_price",
    })


def test_realized_features_are_causal_gap_sensitive_and_asymmetric():
    state = MarketState()
    market = market_fixture(START, "FEATURES")
    state.apply(Event(1, (START - 1801) * NS, None, "market", {"market": market}))
    for second in range(START - 1800, START + 1):
        step = second - (START - 1800)
        price = 80_000 * math.exp(step * 0.000001 + (0.003 if step == 1750 else 0))
        state.apply(ws(index_frame(second, price), second + 0.01))

    features = realized_features(state, market["ticker"], int((START + 0.02) * NS))
    assert features is not None
    assert [row.seconds for row in features.windows] == [60, 300, 1800]
    assert all(row.realized_variance >= row.jump_variation >= 0 for row in features.windows)
    assert features.windows[0].positive_semivariance > features.windows[0].negative_semivariance

    state.index = type(state.index)((row for row in state.index if row[0] != START - 100), maxlen=7200)
    assert realized_features(state, market["ticker"], int((START + 0.02) * NS)) is None


def test_decision_tape_uses_fixed_time_then_first_post_latency_quote_and_result():
    tape = DecisionTape()
    market = market_fixture(START, "TAPE")
    tape.feed(Event(1, (START - 1202) * NS, None, "market", {"market": market}))
    sequence = 0
    for second in range(START - 1201, START + 600):
        if second == START + 590:
            tape.feed(Event(1, int((second + 0.001) * NS), None, "series", {"series": {
                "ticker": "KXBTC15M", "fee_type": "quadratic", "fee_multiplier": 1,
            }}))
            tape.feed(Event(1, int((second + 0.002) * NS), None, "event_metadata", {"event": {
                "event_ticker": market["event_ticker"], "series_ticker": "KXBTC15M",
            }}))
        sequence += 1
        tape.feed(ws(index_frame(second, 80_000 + (second % 7)), second + 0.01))

    sequence += 1
    tape.feed(ws(book_frame(market["ticker"], sequence, ".55", ".53"), START + 600.001))
    key = (market["ticker"], 300)
    row = tape.rows[key]
    assert row["decision_status"] == "usable"
    assert row["jump_feature_status"] == "available"
    assert row["arrival_status"] == "pending"

    sequence += 1
    tape.feed(ws(book_frame(market["ticker"], sequence, ".54", ".52"), START + 600.6))
    assert row["arrival_status"] == "quoted"
    assert row["arrival_quote"]["yes_ask"] == "0.54"

    finalized = {**market, "status": "finalized", "result": "yes"}
    tape.feed(Event(1, (START + 901) * NS, None, "market", {"market": finalized}))
    assert row["result"] == "yes"
    assert tape.report()["scope"].startswith("Read-only")


def _calibration_row(ticker, day, offset, midpoint, result, *, arrival_ask=None):
    base = int(datetime(2026, 1, day, 12, tzinfo=timezone.utc).timestamp() * NS)
    yes_ask = midpoint + 0.01
    no_ask = 1 - midpoint + 0.01
    if arrival_ask is None:
        arrival_ask = yes_ask
    return {
        "ticker": ticker,
        "sample_seconds_left": offset,
        "decision_ns": base,
        "finalized_received_ns": base + 900 * NS,
        "decision_status": "usable",
        "arrival_status": "quoted",
        "result": result,
        "decision_quote": {
            "yes_midpoint": midpoint,
            "yes_ask": str(yes_ask),
            "no_ask": str(no_ask),
            "yes_depth": "10",
            "no_depth": "10",
        },
        "arrival_quote": {
            "yes_midpoint": midpoint,
            "yes_ask": str(arrival_ask),
            "no_ask": str(no_ask),
            "yes_depth": "10",
            "no_depth": "10",
        },
    }


def test_beta_calibration_shrinks_toward_identity_and_reports_uncertainty():
    rows = [
        _calibration_row(f"M-{index}", 1, 180, 0.75 if index % 2 else 0.25,
                         "yes" if index % 2 else "no")
        for index in range(40)
    ]
    model = fit_beta(rows)
    prediction = predict_beta(rows[1], model)
    assert model["training_markets"] == 40
    assert prediction["yes_probability"] > 0.5
    assert 0 < prediction["yes_lower_90"] < prediction["yes_probability"] < 1
    assert 0 < prediction["no_lower_90"] < 1 - prediction["yes_probability"]


def test_development_report_is_expanding_day_ahead_and_cannot_promote(monkeypatch):
    monkeypatch.setattr(market_calibration, "MINIMUM_PRIOR_DATES", 1)
    monkeypatch.setattr(market_calibration, "MINIMUM_TRAINING_MARKETS", 4)
    rows = []
    for day in (1, 2):
        for market in range(4):
            result = "yes" if market % 2 else "no"
            midpoint = 0.75 if result == "yes" else 0.25
            for offset in (300, 180, 60, 30):
                rows.append(_calibration_row(f"D{day}-M{market}", day, offset, midpoint, result))
    report = development_report(rows)
    assert report["model_audit"]["2026-01-01"]["global_available"] is False
    assert report["model_audit"]["2026-01-02"]["global_available"] is True
    assert report["probability_comparison"]["market_beta_global_010"]["rows"] == 16
    assert report["probability_comparison"]["market_beta_time_010"]["rows"] == 16
    assert report["promotion_authorized"] is False
    assert all("passes_all_development_gates" in row for row in report["development_gates"].values())


def test_development_report_first_qualifying_signal_consumes_market(monkeypatch):
    monkeypatch.setattr(market_calibration, "MINIMUM_PRIOR_DATES", 1)
    monkeypatch.setattr(market_calibration, "MINIMUM_TRAINING_MARKETS", 4)
    monkeypatch.setattr(market_calibration, "LOWER_BOUND_Z", 0.0)
    rows = []
    for market in range(4):
        for offset in (300, 180, 60, 30):
            rows.append(_calibration_row(f"TRAIN-{market}", 1, offset, 0.99, "yes"))
    for offset in (300, 180, 60, 30):
        rows.append(_calibration_row("EVAL", 2, offset, 0.90, "yes", arrival_ask=0.92))
    report = development_report(rows)
    for result in report["results"].values():
        assert result["qualifying_attempts"] <= 1
        assert result["settled_fills"] == 0


def test_local_runner_verifies_manifest_resumes_and_completes(tmp_path, monkeypatch):
    dataset = "settlement-runner-test"
    start_segment = 10
    seed_digest = "a" * 64
    source_archives = tmp_path / "source"
    source_archives.mkdir()
    rows = []
    previous_digest = seed_digest
    for segment in (10, 11):
        payload = {"dataset": dataset, "segment": segment, "previous_digest": previous_digest}
        received_ns = segment * NS
        digest = hashlib.sha256(
            bytes.fromhex("0" * 64) + canonical([received_ns, None, "segment_start", payload])
        ).hexdigest()
        archive = source_archives / f"segment-{segment}.zst"
        with archive_writer(archive) as stream:
            stream.write(canonical([1, received_ns, None, "segment_start", payload]) + b"\n")
        rows.append({
            "id": segment,
            "status": "archived",
            "count": 1,
            "digest": digest,
            "previous_digest": previous_digest,
            "archive_key": archive.name,
            "archive_sha": hashlib.sha256(archive.read_bytes()).hexdigest(),
        })
        previous_digest = digest

    monkeypatch.setattr(settlement_runner, "DATASET", dataset)
    monkeypatch.setattr(settlement_runner, "START_SEGMENT", start_segment)
    monkeypatch.setattr(settlement_runner, "SEED_DIGEST", seed_digest)
    monkeypatch.setattr(settlement_runner, "TERMINAL_SEGMENT", 11)
    monkeypatch.setattr(settlement_runner, "TERMINAL_DIGEST", rows[-1]["digest"])
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

    root = tmp_path / "run"
    runner = LocalSettlementResearchRunner(
        manifest, seed_path, root, checkpoint_every=10, bucket=FakeBucket())
    try:
        assert runner.process_next() == "processed"
        assert runner.next_segment == 11
        assert not any((root / "archives").iterdir())
    finally:
        runner.close()

    resumed = LocalSettlementResearchRunner(
        manifest, seed_path, root, checkpoint_every=1, bucket=FakeBucket())
    try:
        assert resumed.next_segment == 11
        assert resumed.process_next() == "processed"
        assert resumed.process_next() == "development_complete"
        report = json.loads((root / "development-report.json").read_text())
        assert report["development_complete"] is True
        assert report["market_calibration_study_010"]["promotion_authorized"] is False
    finally:
        resumed.close()
