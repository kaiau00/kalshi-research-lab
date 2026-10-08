import asyncio
import base64
import json
from decimal import Decimal

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from fastapi.testclient import TestClient
from test_engine import prepared

from demo_execution.app import create_app
from production_execution.client import BASE, ProductionClient, validate_order
from production_execution.journal import Journal
from production_execution.runner import (
    AUTHORIZATION,
    HOLD_AUTHORIZATION,
    HOLD_REVISION,
    Runner,
    exit_payload,
    order_payload,
)


def pem():
    return ed25519.Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def intent(side="no"):
    return order_payload(
        {
            "ticker": "KXBTC15M-26OCT071415-15",
            "limit": Decimal(".38"),
            "quantity": 7,
            "side": side,
        }
    )


def result(payload, fill="1.50"):
    yes_price = Decimal(payload["price"])
    return {
        "client_order_id": payload["client_order_id"],
        "ticker": payload["ticker"],
        "exchange_index": 2,
        "outcome_side": "yes" if payload["side"] == "bid" else "no",
        "subaccount_number": 0,
        "fill_count_fp": fill,
        "remaining_count_fp": "0.00",
        "status": "canceled",
        "taker_fill_cost_dollars": ".5700",
        "maker_fill_cost_dollars": "0",
        "taker_fees_dollars": ".0248",
        "maker_fees_dollars": "0",
        "yes_price_dollars": str(yes_price),
        "no_price_dollars": str(1 - yes_price),
    }


def test_production_client_is_fixed_to_real_host_and_cannot_transfer():
    key = pem()
    calls = []

    def handle(request):
        calls.append(request)
        assert str(request.url).startswith(BASE + "/trade-api/v2/")
        message = (
            request.headers["KALSHI-ACCESS-TIMESTAMP"] + request.method + request.url.path
        ).encode()
        serialization.load_pem_private_key(key, None).public_key().verify(
            base64.b64decode(request.headers["KALSHI-ACCESS-SIGNATURE"]), message
        )
        return httpx.Response(503, json={"code": "temporary"})

    async def check():
        client = ProductionClient("production-test", key, transport=httpx.MockTransport(handle))
        try:
            with pytest.raises(httpx.HTTPStatusError):
                await client.submit(intent())
            assert len(calls) == 1
            with pytest.raises(ValueError, match="early-exit submissions are disabled"):
                await client.submit(
                    exit_payload("KXBTC15M-26OCT071415-15", "yes", 4, Decimal(".61"))
                )
            assert len(calls) == 1
            with pytest.raises(httpx.HTTPStatusError):
                await client.get("/markets/KXBTC15M-26OCT071415-15")
            with pytest.raises(httpx.HTTPStatusError):
                await client.get("/historical/markets/KXBTC15M-26OCT071415-15")
            assert len(calls) == 3
            for path in (
                "/portfolio/intra_exchange_instance_transfer",
                "/portfolio/target_balance_allocation",
                "/markets",
                "https://external-api.demo.kalshi.co/portfolio/orders",
            ):
                with pytest.raises(ValueError):
                    await client.get(path)
            assert len(calls) == 3
        finally:
            await client.close()

    asyncio.run(check())


@pytest.mark.parametrize(
    "change",
    [
        {"exchange_index": 0},
        {"time_in_force": "good_till_canceled"},
        {"ticker": "KXETH15M-X"},
        {"count": "100"},
        {"price": "NaN"},
        {"subaccount": 1},
    ],
)
def test_production_scope_and_three_dollar_cap_are_enforced(change):
    payload = intent()
    payload.update(change)
    with pytest.raises(ValueError):
        validate_order(payload)


def test_reduce_only_exit_uses_opposite_v2_book_side_and_cannot_open_risk():
    yes_exit = exit_payload("KXBTC15M-26OCT071415-15", "yes", 4, Decimal(".61"))
    no_exit = exit_payload("KXBTC15M-26OCT071415-15", "no", 4, Decimal(".72"))
    assert yes_exit["side"] == "ask" and Decimal(yes_exit["price"]) == Decimal(".61")
    assert no_exit["side"] == "bid" and Decimal(no_exit["price"]) == Decimal(".28")
    assert yes_exit["reduce_only"] is True and no_exit["reduce_only"] is True
    validate_order(yes_exit)
    validate_order(no_exit)
    unsafe = dict(yes_exit, reduce_only=False, count="100")
    with pytest.raises(ValueError, match="cost exceeds"):
        validate_order(unsafe)


def test_production_journal_blocks_uncertain_and_foreign_registration(tmp_path):
    path = tmp_path / "orders.sqlite3"
    journal = Journal(path)
    journal.register({"bankroll": "100.00"}, "account-one", "adaptive_volatility", "v1")
    payload = intent()
    journal.intent(payload, {"side": "no"})
    journal.error(payload["client_order_id"], "timeout")
    journal.db.close()

    journal = Journal(path)
    with pytest.raises(RuntimeError, match="Unreconciled"):
        journal.intent(intent("yes"), {})
    with pytest.raises(RuntimeError, match="registration changed"):
        journal.register({"bankroll": "100.00"}, "account-two", "adaptive_volatility", "v1")
    journal.reconcile(payload["client_order_id"], result(payload))
    with pytest.raises(RuntimeError, match="fill limit"):
        journal.intent(intent("yes"), {})
    journal.db.close()


def test_production_journal_tracks_reduce_only_exit_and_realized_pnl(tmp_path):
    journal = Journal(tmp_path / "orders.sqlite3")
    entry = intent("yes")
    journal.intent(entry, {"side": "yes"})
    filled_entry = result(entry, fill="4")
    filled_entry.update(
        taker_fill_cost_dollars="1.5200",
        taker_fees_dollars=".0500",
        yes_price_dollars=".38",
        no_price_dollars=".62",
    )
    journal.reconcile(entry["client_order_id"], filled_entry)
    position = journal.entry_position(entry["ticker"])
    assert position["side"] == "yes" and position["remaining"] == 4

    exit_order = exit_payload(entry["ticker"], "yes", 4, Decimal(".50"))
    journal.exit_intent(exit_order, {"triggers": ["take_profit"]})
    filled_exit = result(exit_order, fill="4")
    filled_exit.update(
        taker_fill_cost_dollars="2.0000",
        taker_fees_dollars=".0700",
        yes_price_dollars=".50",
        no_price_dollars=".50",
    )
    journal.reconcile_exit(exit_order["client_order_id"], filled_exit)
    assert journal.entry_position(entry["ticker"])["remaining"] == 0
    assert journal.exit_pnl() == Decimal(".36")
    assert not journal.open_positions()
    comparison = journal.record_counterfactual(entry["ticker"], "no", finalized_ns=123)
    assert comparison["actual_pnl"] == "0.3600"
    assert comparison["hold_pnl"] == "-1.5700"
    assert comparison["exit_advantage"] == "1.9300"
    assert journal.record_counterfactual(entry["ticker"], "no", finalized_ns=123) == comparison
    journal.db.close()


def test_partial_exit_settlement_reconciles_gross_yes_and_no_counts(tmp_path):
    journal = Journal(tmp_path / "orders.sqlite3")
    entry = order_payload(
        {
            "ticker": "KXBTC15M-26OCT080100-00",
            "limit": Decimal(".11"),
            "quantity": 25,
            "side": "no",
        }
    )
    journal.intent(entry, {"side": "no"})
    filled_entry = result(entry, fill="25")
    filled_entry.update(
        taker_fill_cost_dollars="2.750000",
        taker_fees_dollars=".171400",
        yes_price_dollars=".89",
        no_price_dollars=".11",
    )
    journal.reconcile(entry["client_order_id"], filled_entry)

    first_exit = exit_payload(entry["ticker"], "no", 25, Decimal(".066"))
    journal.exit_intent(first_exit, {"triggers": ["entry_thesis_invalidated"]})
    first_fill = result(first_exit, fill=".02")
    first_fill.update(
        taker_fill_cost_dollars=".018680",
        taker_fees_dollars=".000120",
        yes_price_dollars=".934",
        no_price_dollars=".066",
    )
    journal.reconcile_exit(first_exit["client_order_id"], first_fill)

    second_exit = exit_payload(entry["ticker"], "no", 24, Decimal(".062"))
    journal.exit_intent(second_exit, {"triggers": ["entry_thesis_invalidated"]})
    second_fill = result(second_exit, fill="24")
    second_fill.update(
        taker_fill_cost_dollars="22.488000",
        taker_fees_dollars=".099200",
        yes_price_dollars=".938",
        no_price_dollars=".062",
    )
    journal.reconcile_exit(second_exit["client_order_id"], second_fill)
    assert journal.entry_position(entry["ticker"])["remaining"] == Decimal(".98")

    settlement = {
        "ticker": entry["ticker"],
        "exchange_index": 2,
        "yes_count_fp": "24.02",
        "no_count_fp": "25.00",
        "market_result": "yes",
    }
    journal.settlement(entry["ticker"], settlement)
    assert Decimal(journal.settled()[0]["pnl"]) == Decimal("-.11451888")
    comparison = journal.record_counterfactual(entry["ticker"], "yes", finalized_ns=123)
    assert comparison["actual_pnl"] == "-1.53140000"
    assert comparison["hold_pnl"] == "-2.921400"
    assert comparison["exit_advantage"] == "1.39000000"
    journal.db.close()


def test_arrival_cancellations_count_toward_three_signal_limit(tmp_path):
    journal = Journal(tmp_path / "orders.sqlite3")
    decision = {"ticker": "KXBTC15M-26OCT071415-15", "side": "yes"}
    for index in range(3):
        attempt_id = f"signal-{index}"
        journal.begin_attempt(attempt_id, decision)
        journal.finish_attempt(attempt_id, "arrival_canceled")
    with pytest.raises(RuntimeError, match="attempt or fill limit"):
        journal.begin_attempt("signal-four", decision)
    journal.db.close()


def test_runner_reports_exit_against_official_hold_counterfactual(tmp_path, monkeypatch):
    replay, ticker, _, _ = prepared(risk_per_market="3.00")

    class MarketResultClient(FakeClient):
        def __init__(self):
            self.reads = []

        async def get(self, path, params=None):
            self.reads.append((path, params))
            return {"market": {"ticker": ticker, "status": "finalized", "result": "no"}}

    client = MarketResultClient()
    monkeypatch.setenv("LAB_PRODUCTION_AUTHORIZATION", AUTHORIZATION)
    monkeypatch.setenv("LAB_PRODUCTION_HOLD_AUTHORIZATION", HOLD_AUTHORIZATION)
    runner = Runner(lambda: replay.state, tmp_path, client=client)
    try:
        entry = intent("yes")
        entry["ticker"] = ticker
        runner.journal.intent(entry, {"side": "yes"})
        filled_entry = result(entry, fill="4")
        filled_entry.update(
            taker_fill_cost_dollars="1.5200",
            taker_fees_dollars=".0500",
            yes_price_dollars=".38",
            no_price_dollars=".62",
        )
        runner.journal.reconcile(entry["client_order_id"], filled_entry)
        exit_order = exit_payload(ticker, "yes", 4, Decimal(".50"))
        runner.journal.exit_intent(exit_order, {"triggers": ["take_profit"]})
        filled_exit = result(exit_order, fill="4")
        filled_exit.update(
            taker_fill_cost_dollars="2.0000",
            taker_fees_dollars=".0700",
            yes_price_dollars=".50",
            no_price_dollars=".50",
        )
        runner.journal.reconcile_exit(exit_order["client_order_id"], filled_exit)
        replay.state.markets[ticker].update(status="closed", result="")

        asyncio.run(runner.update_counterfactuals())
        runner.snapshot()

        assert client.reads == [("/markets/" + ticker, None)]
        report = runner.status["exit_counterfactual"]
        assert report["officially_resolved"] == 1
        assert report["pending_official_results"] == 0
        assert report["actual_net_pnl"] == "0.3600"
        assert report["hold_to_settlement_net_pnl"] == "-1.5700"
        assert report["exit_advantage"] == "1.9300"
        assert report["exits_helped"] == 1
        assert report["exits_hurt"] == 0
    finally:
        asyncio.run(runner.client.close())
        runner.journal.db.close()
        runner.lock.close()

class FakeClient:
    key_id = "production-test"

    async def close(self):
        pass


def test_runner_requires_explicit_deployment_token_and_reuses_adaptive_signal(tmp_path, monkeypatch):
    replay, ticker, _, now = prepared(risk_per_market="3.00")
    expected = replay.accounts["adaptive_volatility"]
    replay._decide(expected, ticker, now)
    monkeypatch.delenv("LAB_PRODUCTION_AUTHORIZATION", raising=False)
    with pytest.raises(RuntimeError, match="authorization token"):
        Runner(lambda: replay.state, tmp_path, client=FakeClient())

    monkeypatch.setenv("LAB_PRODUCTION_AUTHORIZATION", AUTHORIZATION)
    monkeypatch.delenv("LAB_PRODUCTION_HOLD_AUTHORIZATION", raising=False)
    with pytest.raises(RuntimeError, match="hold-to-settlement authorization token"):
        Runner(lambda: replay.state, tmp_path, client=FakeClient())

    monkeypatch.setenv("LAB_PRODUCTION_HOLD_AUTHORIZATION", HOLD_AUTHORIZATION)
    runner = Runner(lambda: replay.state, tmp_path, client=FakeClient())
    try:
        signal = runner.signal(ticker, Decimal("100"), now_ns=now)
        for field in ("side", "limit", "quantity", "probability", "edge", "arrival_ns"):
            assert signal[field] == expected.pending[ticker][field]
        assert runner.status["strategy"] == "adaptive_volatility"
        assert runner.status["risk_per_market"] == "3.00"
        assert runner.status["bankroll_baseline"] == "100.00"
        assert runner.status["position_policy_revision"] == HOLD_REVISION
        assert runner.status["strategy_parameters"]["early_exit_submission"] == "disabled"
        registration = json.loads(
            runner.journal.db.execute(
                "SELECT value FROM metadata WHERE key='registration'"
            ).fetchone()[0]
        )
        assert registration["environment"] == "production"
        assert registration["exchange_index"] == 2
        hold_policy = json.loads(
            runner.journal.db.execute(
                "SELECT value FROM metadata WHERE key='hold_policy_registration'"
            ).fetchone()[0]
        )
        assert hold_policy["revision"] == HOLD_REVISION
        assert hold_policy["position_policy"] == "hold_to_official_settlement"
    finally:
        asyncio.run(runner.client.close())
        runner.journal.db.close()
        runner.lock.close()


def test_live_position_monitor_holds_and_has_no_exit_submission_path(tmp_path, monkeypatch):
    replay, ticker, _, _ = prepared(risk_per_market="3.00")
    monkeypatch.setenv("LAB_PRODUCTION_AUTHORIZATION", AUTHORIZATION)
    monkeypatch.setenv("LAB_PRODUCTION_HOLD_AUTHORIZATION", HOLD_AUTHORIZATION)
    runner = Runner(lambda: replay.state, tmp_path, client=FakeClient())
    try:
        entry = intent("yes")
        entry["ticker"] = ticker
        runner.journal.intent(entry, {"side": "yes"})
        filled_entry = result(entry, fill="4")
        filled_entry.update(
            taker_fill_cost_dollars="1.5200",
            taker_fees_dollars=".0500",
            yes_price_dollars=".38",
            no_price_dollars=".62",
        )
        runner.journal.reconcile(entry["client_order_id"], filled_entry)

        managed = asyncio.run(
            runner.manage_position([{"ticker": ticker, "position_fp": "4.00"}])
        )

        assert managed is True
        assert runner.status["state"] == "holding_to_settlement"
        assert runner.status["open_position"]["quantity"] == "4"
        assert runner.journal.exit_rows() == []
    finally:
        asyncio.run(runner.client.close())
        runner.journal.db.close()
        runner.lock.close()


def test_production_status_is_protected_and_disabled_by_default(monkeypatch):
    monkeypatch.delenv("LAB_PRODUCTION_ENABLED", raising=False)
    monkeypatch.setenv("LAB_DASHBOARD_PASSWORD", "test-password-long-enough")
    with TestClient(create_app(record=False)) as client:
        assert client.get("/api/production/status").status_code == 401
        result = client.get(
            "/api/production/status", auth=("lab", "test-password-long-enough")
        )
        assert result.json()["state"] == "disabled"
