from __future__ import annotations

import base64
import os
import re
import time
from decimal import ROUND_CEILING, Decimal

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

BASE = "https://external-api.kalshi.com"
PREFIX = "/trade-api/v2"
TICKER = re.compile(r"KXBTC15M-[A-Z0-9-]+\Z")


class ProductionClient:
    """Narrow production client: portfolio reads and guarded IOC orders."""

    def __init__(self, key_id=None, pem=None, *, max_order_cost="1.00", transport=None):
        self.key_id = key_id or os.environ["KALSHI_API_KEY_ID"]
        if pem is None:
            pem_text = os.environ.get("KALSHI_PRIVATE_KEY_PEM", "")
            b64 = os.environ.get("KALSHI_PRIVATE_KEY_B64", "")
            if not (pem_text or b64):
                raise ValueError("Production signing key is missing")
            pem = pem_text.encode() if pem_text else base64.b64decode(b64, validate=True)
        self.key = serialization.load_pem_private_key(pem, password=None)
        if not isinstance(self.key, (rsa.RSAPrivateKey, ed25519.Ed25519PrivateKey)):
            raise ValueError("Unsupported production signing key")
        self.max_order_cost = Decimal(max_order_cost)
        if not self.max_order_cost.is_finite() or self.max_order_cost <= 0:
            raise ValueError("Invalid production order cost limit")
        self.http = httpx.AsyncClient(timeout=10, follow_redirects=False, transport=transport)

    def headers(self, method, path):
        stamp = str(int(time.time() * 1000))
        message = (stamp + method + path.split("?")[0]).encode()
        signature = (
            self.key.sign(message)
            if isinstance(self.key, ed25519.Ed25519PrivateKey)
            else self.key.sign(
                message,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
                hashes.SHA256(),
            )
        )
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": stamp,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
        }

    async def get(self, path, params=None):
        market_result = re.fullmatch(r"/(?:historical/)?markets/(KXBTC15M-[A-Z0-9-]+)", path)
        if path not in (
            "/exchange/status",
            "/portfolio/balance",
            "/portfolio/orders",
            "/portfolio/positions",
            "/portfolio/settlements",
        ) and not market_result:
            raise ValueError("Unsupported production read path")
        signed_path = PREFIX + path
        response = await self.http.get(
            BASE + signed_path,
            params=params,
            headers=self.headers("GET", signed_path),
        )
        response.raise_for_status()
        return response.json()

    async def submit(self, payload):
        validate_order(payload, self.max_order_cost)
        if payload.get("reduce_only"):
            raise ValueError("Production early-exit submissions are disabled")
        path = PREFIX + "/portfolio/events/orders"
        response = await self.http.post(
            BASE + path,
            headers=self.headers("POST", path),
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def close(self):
        await self.http.aclose()


def validate_order(payload, max_order_cost=Decimal("1.00")):
    required = {
        "ticker",
        "client_order_id",
        "side",
        "count",
        "price",
        "time_in_force",
        "self_trade_prevention_type",
        "exchange_index",
        "subaccount",
    }
    allowed = required | {"reduce_only"}
    if set(payload) - allowed or not required <= set(payload) or not TICKER.fullmatch(payload["ticker"]):
        raise ValueError("Only BTC 15-minute production IOC orders are supported")
    reduce_only = payload.get("reduce_only", False)
    if (
        payload["side"] not in ("bid", "ask")
        or payload["time_in_force"] != "immediate_or_cancel"
        or payload["self_trade_prevention_type"] != "taker_at_cross"
        or payload["exchange_index"] != 2
        or payload["subaccount"] != 0
        or not isinstance(reduce_only, bool)
    ):
        raise ValueError("Invalid production execution scope")
    count, price = Decimal(payload["count"]), Decimal(payload["price"])
    if (
        not count.is_finite()
        or not price.is_finite()
        or count != int(count)
        or not 1 <= count <= 10000
        or not 0 < price < 1
    ):
        raise ValueError("Invalid production order price or quantity")
    if not reduce_only:
        outcome_price = price if payload["side"] == "bid" else 1 - price
        fee = (Decimal(".07") * count * outcome_price * (1 - outcome_price)).quantize(
            Decimal(".000001"), rounding=ROUND_CEILING
        )
        limit = Decimal(max_order_cost)
        if (count * outcome_price + fee).quantize(Decimal(".0001"), rounding=ROUND_CEILING) > limit:
            raise ValueError("Production order cost exceeds configured limit")
    if not re.fullmatch(r"prod-[a-f0-9]{32}", payload["client_order_id"]):
        raise ValueError("Invalid persistent production client order ID")
