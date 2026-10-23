"""Narrow Kalshi Demo client for the HFT experiment.

There is no production host fallback and no generic write method. Create and
cancel requests are never retried automatically.
"""

from __future__ import annotations

import base64
import os
import re
import time
from decimal import Decimal

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

BASE = "https://external-api.demo.kalshi.co"
READ_BASES = (BASE, "https://demo-api.kalshi.co")
WS = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"
PREFIX = "/trade-api/v2"
TICKER = re.compile(r"KXBTC15M-[A-Z0-9-]+\Z")
ORDER_ID = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
CLIENT_ID = re.compile(r"hft-[a-f0-9]{32}\Z")


class DemoHFTClient:
    def __init__(self, key_id=None, pem=None, *, transport=None):
        self.key_id = key_id or os.environ["KALSHI_DEMO_KEY_ID"]
        raw = pem or base64.b64decode(os.environ["KALSHI_DEMO_PRIVATE_KEY_B64"], validate=True)
        self.key = serialization.load_pem_private_key(raw, password=None)
        if not isinstance(self.key, (rsa.RSAPrivateKey, ed25519.Ed25519PrivateKey)):
            raise ValueError("Unsupported demo signing key")
        self.http = httpx.AsyncClient(timeout=10, follow_redirects=False, transport=transport)

    def headers(self, method: str, path: str) -> dict:
        stamp = str(int(time.time() * 1000))
        signed_path = path.split("?")[0]
        message = (stamp + method + signed_path).encode()
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

    @staticmethod
    def _read_allowed(path: str) -> bool:
        return bool(
            re.fullmatch(r"/markets(?:/KXBTC15M-[A-Z0-9-]+(?:/orderbook)?)?", path)
            or re.fullmatch(r"/events/KXBTC15M-[A-Z0-9-]+", path)
            or re.fullmatch(r"/portfolio/orders/[A-Za-z0-9_-]{8,128}", path)
            or path
            in {
                "/series/KXBTC15M",
                "/exchange/status",
                "/portfolio/balance",
                "/portfolio/orders",
                "/portfolio/positions",
                "/portfolio/settlements",
                "/portfolio/fills",
            }
        )

    async def get(self, path: str, params=None) -> dict:
        if not self._read_allowed(path):
            raise ValueError("Unsupported HFT demo read path")
        signed_path = PREFIX + path
        for index, base in enumerate(READ_BASES):
            try:
                response = await self.http.get(
                    base + signed_path,
                    params=params,
                    headers=self.headers("GET", signed_path),
                )
            except httpx.RequestError:
                if index + 1 < len(READ_BASES):
                    continue
                raise
            if response.status_code < 500 or index + 1 == len(READ_BASES):
                response.raise_for_status()
                return response.json()
        raise RuntimeError("Unreachable HFT demo read fallback state")

    async def create(self, payload: dict) -> dict:
        validate_maker_order(payload)
        path = PREFIX + "/portfolio/events/orders"
        response = await self.http.post(
            BASE + path,
            headers=self.headers("POST", path),
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def cancel(self, order_id: str, ticker: str) -> dict:
        if not ORDER_ID.fullmatch(order_id) or not TICKER.fullmatch(ticker):
            raise ValueError("Invalid HFT demo cancellation identity")
        path = PREFIX + "/portfolio/events/orders/" + order_id
        response = await self.http.delete(
            BASE + path,
            params={"market_ticker": ticker, "exchange_index": 2},
            headers=self.headers("DELETE", path),
        )
        response.raise_for_status()
        return response.json()

    async def close(self):
        await self.http.aclose()


def validate_maker_order(payload: dict) -> None:
    required = {
        "ticker",
        "client_order_id",
        "side",
        "count",
        "price",
        "time_in_force",
        "expiration_time",
        "self_trade_prevention_type",
        "post_only",
        "cancel_order_on_pause",
        "reduce_only",
        "exchange_index",
        "subaccount",
    }
    if set(payload) != required:
        raise ValueError("Unexpected HFT demo order fields")
    if not TICKER.fullmatch(str(payload["ticker"])) or not CLIENT_ID.fullmatch(
        str(payload["client_order_id"])
    ):
        raise ValueError("Invalid HFT demo order identity")
    if (
        payload["side"] not in {"bid", "ask"}
        or payload["time_in_force"] != "good_till_canceled"
        or payload["self_trade_prevention_type"] != "taker_at_cross"
        or payload["post_only"] is not True
        or payload["cancel_order_on_pause"] is not True
        or payload["reduce_only"] is not False
        or payload["exchange_index"] != 2
        or payload["subaccount"] != 0
    ):
        raise ValueError("HFT demo maker safety controls changed")
    count = Decimal(str(payload["count"]))
    price = Decimal(str(payload["price"]))
    expiration = payload["expiration_time"]
    if count != 1 or not price.is_finite() or not Decimal("0") < price < Decimal("1"):
        raise ValueError("HFT demo order quantity or price is invalid")
    if not isinstance(expiration, int) or expiration <= int(time.time()):
        raise ValueError("HFT demo order expiration is invalid")

