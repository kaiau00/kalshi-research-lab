from __future__ import annotations

import base64
import os
import re
import time
from decimal import ROUND_CEILING, Decimal

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

BASE = 'https://external-api.demo.kalshi.co'
READ_BASES = (BASE, 'https://demo-api.kalshi.co')
WS = 'wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2'
PREFIX = '/trade-api/v2'
TICKER = re.compile(r'KXBTC15M-[A-Z0-9-]+\Z')


class DemoClient:
    """Fixed demo hosts only, with no production fallback, redirects, or write retries."""

    def __init__(self, key_id=None, pem=None, *, max_order_cost='1.00', transport=None):
        self.key_id = key_id or os.environ['KALSHI_DEMO_KEY_ID']
        raw = pem or base64.b64decode(os.environ['KALSHI_DEMO_PRIVATE_KEY_B64'], validate=True)
        self.key = serialization.load_pem_private_key(raw, password=None)
        if not isinstance(self.key, (rsa.RSAPrivateKey, ed25519.Ed25519PrivateKey)):
            raise ValueError('Unsupported demo signing key')
        self.max_order_cost = Decimal(max_order_cost)
        if not self.max_order_cost.is_finite() or self.max_order_cost <= 0:
            raise ValueError('Invalid demo order cost limit')
        self.http = httpx.AsyncClient(timeout=10, follow_redirects=False, transport=transport)

    def headers(self, method, path):
        stamp = str(int(time.time() * 1000))
        msg = (stamp + method + path.split('?')[0]).encode()
        sig = (self.key.sign(msg) if isinstance(self.key, ed25519.Ed25519PrivateKey) else
               self.key.sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
                             hashes.SHA256()))
        return {'KALSHI-ACCESS-KEY': self.key_id, 'KALSHI-ACCESS-TIMESTAMP': stamp,
                'KALSHI-ACCESS-SIGNATURE': base64.b64encode(sig).decode()}

    async def get(self, path, params=None):
        allowed = (re.fullmatch(r'/markets(?:/KXBTC15M-[A-Z0-9-]+(?:/orderbook)?)?', path)
                   or re.fullmatch(r'/events/KXBTC15M-[A-Z0-9-]+', path)
                   or path in ('/series/KXBTC15M', '/exchange/status', '/portfolio/balance',
                               '/portfolio/orders', '/portfolio/positions', '/portfolio/settlements'))
        if not allowed:
            raise ValueError('Unsupported demo read path')
        for index, base in enumerate(READ_BASES):
            try:
                response = await self.http.get(base + PREFIX + path, params=params,
                                               headers=self.headers('GET', PREFIX + path))
            except httpx.RequestError:
                if index + 1 < len(READ_BASES):
                    continue
                raise
            if response.status_code < 500 or index + 1 == len(READ_BASES):
                response.raise_for_status()
                return response.json()
        raise RuntimeError('Unreachable demo read fallback state')

    async def submit(self, payload):
        validate_order(payload, self.max_order_cost)
        path = PREFIX + '/portfolio/events/orders'
        response = await self.http.post(BASE + path, headers=self.headers('POST', path), json=payload)
        response.raise_for_status()
        return response.json()

    async def close(self):
        await self.http.aclose()


def validate_order(p, max_order_cost=Decimal('1.00')):
    required = {'ticker', 'client_order_id', 'side', 'count', 'price', 'time_in_force',
                'self_trade_prevention_type', 'exchange_index', 'subaccount'}
    if set(p) != required or not TICKER.fullmatch(p['ticker']):
        raise ValueError('Only BTC demo IOC orders are supported')
    if (p['side'] not in ('bid', 'ask') or p['time_in_force'] != 'immediate_or_cancel'
            or p['self_trade_prevention_type'] != 'taker_at_cross'
            or p['exchange_index'] != 2 or p['subaccount'] != 0):
        raise ValueError('Invalid demo execution scope')
    count, price = Decimal(p['count']), Decimal(p['price'])
    if (not count.is_finite() or not price.is_finite() or count != int(count)
            or not 1 <= count <= 10000 or not 0 < price < 1):
        raise ValueError('Invalid demo order price/quantity')
    cost = price if p['side'] == 'bid' else 1-price
    fee = (Decimal('.07') * count * cost * (1-cost)).quantize(Decimal('.000001'), rounding=ROUND_CEILING)
    limit = Decimal(max_order_cost)
    if not limit.is_finite() or limit <= 0:
        raise ValueError('Invalid demo order cost limit')
    if (count * cost + fee).quantize(Decimal('.0001'), rounding=ROUND_CEILING) > limit:
        raise ValueError('Demo order cost exceeds configured limit')
    if not re.fullmatch(r'fv-[a-f0-9]{32}', p['client_order_id']):
        raise ValueError('Invalid persistent client order ID')
