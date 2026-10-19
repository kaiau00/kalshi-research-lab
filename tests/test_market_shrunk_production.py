import asyncio
from decimal import Decimal

import pytest
from test_market import NS, START, warmed_state, ws

from market_shrunk_production.registration import (
    AUTHORIZATION,
    HOLD_AUTHORIZATION,
    RISK_AUTHORIZATION,
)
from market_shrunk_production.runner import (
    ENTRY_PAUSE_FILE,
    Runner,
    forecast_at_completed_minute,
    half_kelly_target,
    minute_boundary,
    order_payload,
    quantity_for_budget,
)
from production_execution.client import validate_order
from research_lab.demo import book_frame
from research_lab.settings import Experiment


class FakeClient:
    key_id = "market-shrunk-production-test"

    async def close(self):
        pass


class PausedClient(FakeClient):
    def __init__(self):
        self.reads = []
        self.submissions = []

    async def get(self, path, params=None):
        self.reads.append((path, params))
        if path == "/portfolio/positions":
            return {"market_positions": [], "cursor": ""}
        if path == "/portfolio/balance":
            return {"balance_dollars": "100.0000", "portfolio_value": 0}
        raise AssertionError(f"unexpected read: {path}")

    async def submit(self, payload):
        self.submissions.append(payload)
        raise AssertionError("paused runner submitted an order")


def authorize(monkeypatch):
    monkeypatch.setenv("LAB_MARKET_SHRUNK_PRODUCTION_AUTHORIZATION", AUTHORIZATION)
    monkeypatch.setenv("LAB_MARKET_SHRUNK_RISK_AUTHORIZATION", RISK_AUTHORIZATION)
    monkeypatch.setenv("LAB_MARKET_SHRUNK_HOLD_AUTHORIZATION", HOLD_AUTHORIZATION)


def test_minute_clock_only_opens_just_after_completed_boundaries():
    close_ns = (START + 900) * NS
    assert minute_boundary((START + 720) * NS, close_ns) == START + 720
    assert minute_boundary(int((START + 723.9) * NS), close_ns) == START + 720
    assert minute_boundary((START + 724) * NS, close_ns) is None
    assert minute_boundary((START + 600) * NS, close_ns) == START + 600
    assert minute_boundary((START + 900) * NS, close_ns) is None


def test_completed_minute_forecast_excludes_boundary_second():
    state, ticker = warmed_state(720)
    cfg = Experiment(risk_per_market="3.00", min_edge=.005)
    result = forecast_at_completed_minute(
        state, ticker, START + 720, int((START + 720.2) * NS), cfg
    )
    assert result is not None
    assert result["decision_boundary_second"] == START + 720
    assert result["forecast_cutoff_second"] == START + 719
    assert result["variance_blend"] == "90% fast + 10% slow"


def test_half_kelly_uses_cash_and_three_dollar_cap_with_integer_fees():
    cfg = Experiment(risk_per_market="3.00", min_edge=.005)
    target, full = half_kelly_target(.60, Decimal(".45"), Decimal("100"), cfg)
    assert full > 0
    assert target == Decimal("3.00")
    quantity = quantity_for_budget(Decimal(".45"), target, cfg)
    assert quantity == 6
    assert quantity_for_budget(Decimal(".79"), Decimal(".50"), cfg) == 0


def test_fresh_runner_is_paused_and_signal_matches_frozen_filters(tmp_path, monkeypatch):
    authorize(monkeypatch)
    state, ticker = warmed_state(720)
    state.apply(ws(book_frame(ticker, 1, ".46", ".45", "20"), START + 720.1))
    runner = Runner(lambda: state, tmp_path, client=FakeClient())
    monkeypatch.setattr(
        "market_shrunk_production.runner.forecast_at_completed_minute",
        lambda *_args, **_kwargs: {
            "yes_probability": .52,
            "decision_boundary_second": START + 720,
            "forecast_cutoff_second": START + 719,
        },
    )
    try:
        assert (tmp_path / ENTRY_PAUSE_FILE).exists()
        assert runner.status["strategy"] == "market_shrunk_half_kelly_001"
        decision = runner.signal(ticker, Decimal("100"), int((START + 720.2) * NS))
        assert decision is not None
        assert decision["side"] == "yes"
        assert decision["limit"] == Decimal(".46")
        assert Decimal("0") < decision["target_budget"] <= Decimal("3.00")
        assert decision["reservation"] <= Decimal("3.00")
        payload = order_payload(decision)
        validate_order(payload, Decimal("3.00"))
        assert Decimal(payload["count"]) <= 20
        runner.journal.begin_attempt("signal-test", decision)
        state.apply(ws(book_frame(ticker, 2, ".46", ".45", "20"), START + 780.1))
        assert runner.signal(ticker, Decimal("100"), int((START + 780.2) * NS)) is None
        assert runner.rejections["market_already_attempted"] == 1
    finally:
        asyncio.run(runner.client.close())
        runner.journal.db.close()
        runner.lock.close()


def test_runner_refuses_missing_explicit_authorization(tmp_path, monkeypatch):
    state, _ = warmed_state(720)
    monkeypatch.delenv("LAB_MARKET_SHRUNK_PRODUCTION_AUTHORIZATION", raising=False)
    with pytest.raises(RuntimeError, match="authorization token"):
        Runner(lambda: state, tmp_path, client=FakeClient())


def test_fresh_runner_pause_blocks_signal_evaluation_and_submission(tmp_path, monkeypatch):
    authorize(monkeypatch)
    state, _ = warmed_state(720)
    client = PausedClient()
    runner = Runner(lambda: state, tmp_path, client=client)
    runner.signal = lambda *_args, **_kwargs: pytest.fail("paused runner evaluated a signal")
    try:
        asyncio.run(runner.step())
        runner.snapshot()
        assert runner.status["state"] == "entries_paused"
        assert runner.status["entries_paused"] is True
        assert client.submissions == []
        assert [path for path, _ in client.reads] == [
            "/portfolio/positions",
            "/portfolio/balance",
        ]
    finally:
        asyncio.run(runner.client.close())
        runner.journal.db.close()
        runner.lock.close()
