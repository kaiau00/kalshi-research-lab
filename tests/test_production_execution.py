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
from production_execution.runner import AUTHORIZATION, Runner, order_payload


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
            for path in (
                "/portfolio/intra_exchange_instance_transfer",
                "/portfolio/target_balance_allocation",
                "/markets",
                "https://external-api.demo.kalshi.co/portfolio/orders",
            ):
                with pytest.raises(ValueError):
                    await client.get(path)
            assert len(calls) == 1
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
    runner = Runner(lambda: replay.state, tmp_path, client=FakeClient())
    try:
        signal = runner.signal(ticker, Decimal("100"), now_ns=now)
        for field in ("side", "limit", "quantity", "probability", "edge", "arrival_ns"):
            assert signal[field] == expected.pending[ticker][field]
        assert runner.status["strategy"] == "adaptive_volatility"
        assert runner.status["risk_per_market"] == "3.00"
        assert runner.status["bankroll_baseline"] == "100.00"
        registration = json.loads(
            runner.journal.db.execute(
                "SELECT value FROM metadata WHERE key='registration'"
            ).fetchone()[0]
        )
        assert registration["environment"] == "production"
        assert registration["exchange_index"] == 2
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
