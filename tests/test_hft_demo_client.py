import asyncio
import base64
import time

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from hft_demo.client import BASE, DemoHFTClient, validate_maker_order


def pem():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())


def payload(**overrides):
    value = {
        "ticker": "KXBTC15M-TEST",
        "client_order_id": "hft-" + "a" * 32,
        "side": "bid",
        "count": "1",
        "price": "0.45",
        "time_in_force": "good_till_canceled",
        "expiration_time": int(time.time()) + 3,
        "self_trade_prevention_type": "taker_at_cross",
        "post_only": True,
        "cancel_order_on_pause": True,
        "reduce_only": False,
        "exchange_index": 2,
        "subaccount": 0,
    }
    value.update(overrides)
    return value


def test_maker_payload_is_one_contract_post_only_demo_scope():
    validate_maker_order(payload())
    for changed in (
        {"count": "2"},
        {"post_only": False},
        {"time_in_force": "immediate_or_cancel"},
        {"exchange_index": 1},
        {"ticker": "OTHER"},
    ):
        with pytest.raises(ValueError):
            validate_maker_order(payload(**changed))


def test_client_uses_demo_host_and_exact_create_cancel_paths(monkeypatch):
    seen = []

    def handle(request):
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "order_id": "order-12345678",
                    "client_order_id": "hft-" + "a" * 32,
                    "fill_count": "0.00",
                    "remaining_count": "1.00",
                    "ts_ms": 1,
                },
            )
        return httpx.Response(
            200,
            json={
                "order_id": "order-12345678",
                "client_order_id": "hft-" + "a" * 32,
                "reduced_by": "1.00",
                "ts_ms": 2,
            },
        )

    monkeypatch.setenv("KALSHI_DEMO_KEY_ID", "demo-key")
    monkeypatch.setenv("KALSHI_DEMO_PRIVATE_KEY_B64", base64.b64encode(pem()).decode())
    async def run():
        client = DemoHFTClient(transport=httpx.MockTransport(handle))
        try:
            await client.create(payload())
            await client.cancel("order-12345678", "KXBTC15M-TEST")
        finally:
            await client.close()

    asyncio.run(run())
    assert [request.method for request in seen] == ["POST", "DELETE"]
    assert all(str(request.url).startswith(BASE) for request in seen)
    assert seen[0].url.path == "/trade-api/v2/portfolio/events/orders"
    assert seen[1].url.path.endswith("/portfolio/events/orders/order-12345678")
    assert seen[1].url.params["exchange_index"] == "2"


def test_private_key_environment_remains_demo_specific(monkeypatch):
    monkeypatch.delenv("KALSHI_DEMO_PRIVATE_KEY_B64", raising=False)
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_B64", base64.b64encode(pem()).decode())
    with pytest.raises(KeyError):
        DemoHFTClient(key_id="demo-key")
