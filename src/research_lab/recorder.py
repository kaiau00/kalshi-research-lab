from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import uuid
import zlib
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from websockets.asyncio.client import connect

from .market import MarketState, epoch_ns
from .storage import Store

LOG = logging.getLogger(__name__)
REST_BASE = "https://external-api.kalshi.com/trade-api/v2"
WS_URL = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
SERIES = "KXBTC15M"


class MarketDataClient:
    """Market data only. No account, portfolio, or exchange order methods."""

    def __init__(self):
        self.http = httpx.AsyncClient(timeout=20, follow_redirects=False)

    async def get(self, path, params=None):
        if not path.startswith(("/markets", "/historical/", "/series/", "/exchange/")) or ":" in path:
            raise ValueError("Only market-data GET endpoints are allowed")
        for attempt in range(4):
            response = await self.http.get(REST_BASE + path, params=params)
            if response.status_code == 429 or response.status_code >= 500:
                await asyncio.sleep(min(10, 2 ** attempt))
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError("Market-data retries exhausted")

    async def markets(self, **params):
        return await self.get("/markets", {"series_ticker": SERIES, "limit": 200, **params})

    async def close(self):
        await self.http.aclose()


def load_signer():
    key_id = os.environ.get("KALSHI_API_KEY_ID", "").strip()
    pem = os.environ.get("KALSHI_PRIVATE_KEY_PEM", "")
    b64 = os.environ.get("KALSHI_PRIVATE_KEY_B64", "")
    key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "")
    if not key_id or not (pem or b64 or key_path):
        return None
    raw = pem.encode() if pem else base64.b64decode(b64, validate=True) if b64 else Path(key_path).read_bytes()
    key = serialization.load_pem_private_key(raw, password=None)

    def headers():
        stamp = str(int(time.time() * 1000))
        message = (stamp + "GET" + "/trade-api/ws/v2").encode()
        signature = key.sign(message, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256())
        return {"KALSHI-ACCESS-KEY": key_id, "KALSHI-ACCESS-TIMESTAMP": stamp,
                "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode()}
    return headers


class Recorder:
    def __init__(self, path: Path):
        self.segmented = os.environ.get('LAB_SEGMENTED') == '1'
        if self.segmented:
            from .segments import SegmentedStore
            self.store = SegmentedStore(path.parent)
            latest = self.store.latest_markets()
        else:
            self.store = Store(path)
            latest = [json.loads(zlib.decompress(row[0])) for row in
                      self.store.conn.execute('SELECT payload FROM latest_markets')]
        if self.store.prefix()['last_event_id'] == 0:
            from .research import source_hash
            from .settings import Experiment
            self.store.append('experiment_registration', {'config': Experiment().to_dict(),
                                                          'source_sha256': source_hash()})
            self.store.commit()
        self.client = MarketDataClient()
        self.current, self.watch = set(), set()
        self.pending = {m['ticker'] for m in latest if m.get('status') != 'finalized'}
        self.known = {m['ticker']: m for m in latest}
        self.state = MarketState()
        self.status = {'mode': 'waiting_for_credentials', 'last_discovery_ns': None,
                       'last_ws_ns': None, 'last_benchmark_ns': None, 'error': None,
                       'book_connection': 'waiting', 'benchmark_connection': 'waiting'}
        self.max_bytes = int(os.environ.get('LAB_MAX_STORAGE_BYTES', '2000000000'))
        self.last_commit = time.monotonic()
        self.last_series = 0

    def append(self, kind, payload, source_ns=None):
        event = self.store.append(kind, payload, source_ns=source_ns)
        self.state.apply(event)
        if time.monotonic() - self.last_commit >= 1:
            if self.store.stats()['bytes'] >= self.max_bytes:
                raise RuntimeError('storage_limit_reached')
            if self.segmented:
                from .segments import enough_disk
                if not enough_disk(self.store.root):
                    raise RuntimeError('disk_reserve_reached')
            self.store.commit()
            self.last_commit = time.monotonic()
        return event

    def remember(self, market):
        ticker = market['ticker']
        old = self.known.get(ticker)
        if old and old.get('result') in ('yes', 'no') and market.get('result') != old['result']:
            self.append('outcome_revision', {'ticker': ticker, 'previous': old['result'],
                                            'current': market.get('result')})
        self.append('market', {'market': market})
        self.known[ticker] = market
        if market.get('status') == 'finalized':
            self.pending.discard(ticker)
        else:
            self.pending.add(ticker)

    async def discover(self):
        while True:
            try:
                now = time.time()
                # Includes upcoming markets so their book can be subscribed before open.
                result = await self.client.markets(min_close_ts=int(now)-60, max_close_ts=int(now)+1800)
                if result.get('cursor'):
                    raise RuntimeError('Unexpected BTC discovery pagination')
                current, watch = set(), set()
                for market in result.get('markets', []):
                    self.remember(market)
                    start, close = epoch_ns(market['open_time'])/1e9, epoch_ns(market['close_time'])/1e9
                    if close > now and market.get('status') in ('active', 'initialized', 'inactive'):
                        watch.add(market['ticker'])
                        if start <= now:
                            current.add(market['ticker'])
                self.current, self.watch = current, watch
                self.status['last_discovery_ns'] = time.time_ns()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.status['error'] = str(exc) if str(exc).endswith('_reached') else type(exc).__name__
                if str(exc).endswith('_reached'):
                    raise
            # Faster near boundaries, moderate polling elsewhere. Resolution never blocks discovery.
            phase = time.time() % 900
            await asyncio.sleep(1 if phase < 60 or phase > 840 else 5)

    async def resolve(self):
        while True:
            if time.monotonic() - self.last_series >= 900:
                try:
                    result = await self.client.get('/series/' + SERIES)
                    self.append('series', {'series': result['series']})
                    self.last_series = time.monotonic()
                except (httpx.HTTPError, RuntimeError) as exc:
                    if str(exc).endswith('_reached'):
                        raise
            # Keep refreshing determined outcomes until the exchange finalizes them.
            for ticker in sorted(self.pending):
                if epoch_ns(self.known[ticker]['close_time']) > time.time_ns():
                    continue
                try:
                    try:
                        result = await self.client.get('/markets/' + ticker)
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code != 404:
                            raise
                        result = await self.client.get('/historical/markets/' + ticker)
                    self.remember(result.get('market', result))
                except (httpx.HTTPError, RuntimeError) as exc:
                    if str(exc).endswith('_reached'):
                        raise
                    self.append('resolution_error', {'ticker': ticker, 'error': type(exc).__name__})
                await asyncio.sleep(.1)
            await asyncio.sleep(3)

    async def stream(self, channel):
        benchmark = channel == 'benchmark'
        delay = 1
        while True:
            try:
                signer = load_signer()
                if signer is None:
                    await asyncio.sleep(10)
                    continue
                if not benchmark and not self.watch:
                    await asyncio.sleep(1)
                    continue
                session = uuid.uuid4().hex
                seq, sid, request_id = {}, None, 1
                subscribed = set(self.watch) if not benchmark else set()
                self.status[channel + '_connection'] = 'connecting'
                async with connect(WS_URL, additional_headers=signer(), ping_interval=15,
                                   ping_timeout=15, max_size=4*1024*1024, max_queue=128) as ws:
                    self.append('gap', {'reason': 'new_stream_session', 'session': session, 'stream': channel})
                    params = ({'channels': ['cfbenchmarks_value'], 'index_ids': ['BRTI']} if benchmark else
                              {'channels': ['orderbook_delta'], 'market_tickers': sorted(subscribed), 'use_yes_price': True})
                    await ws.send(json.dumps({'id': 1, 'cmd': 'subscribe', 'params': params}))
                    last_data = time.monotonic()
                    while True:
                        if not benchmark and sid is not None:
                            add = self.watch - subscribed
                            remove = subscribed - self.watch
                            # Retain the final closed book while idle; never unsubscribe BRTI.
                            for action, tickers in [('add_markets', add), ('delete_markets', remove if self.watch else set())]:
                                if tickers:
                                    request_id += 1
                                    await ws.send(json.dumps({'id': request_id, 'cmd': 'update_subscription',
                                        'params': {'sid': sid, 'market_tickers': sorted(tickers), 'action': action}}))
                                    if action == 'add_markets':
                                        subscribed |= tickers
                                    else:
                                        subscribed -= tickers
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=.25)
                        except TimeoutError:
                            if time.monotonic()-last_data > 30 and (benchmark or self.current):
                                raise RuntimeError('stream_no_data')
                            continue
                        last_data = time.monotonic()
                        frame = json.loads(raw)
                        msg = frame.get('msg') or {}
                        source_ns = int(msg['ts_ms'])*1_000_000 if msg.get('ts_ms') else None
                        if frame.get('type') == 'subscribed':
                            sid = msg.get('sid', frame.get('sid'))
                        if frame.get('type') == 'cfbenchmarks_value':
                            data = json.loads(msg['data']) if isinstance(msg['data'], str) else msg['data']
                            source_ns = int(data['time'])*1_000_000
                            self.status['last_benchmark_ns'] = time.time_ns()
                        self.append('ws', {'frame': frame, 'session': session,
                                          'book_convention': 'yes_price'}, source_ns)
                        if frame.get('type') == 'error':
                            raise RuntimeError('subscription_error')
                        if 'sid' in frame and 'seq' in frame:
                            stream_id, cur = int(frame['sid']), int(frame['seq'])
                            if stream_id in seq and cur != seq[stream_id]+1:
                                raise RuntimeError('sequence_gap')
                            seq[stream_id] = cur
                        self.status.update(last_ws_ns=time.time_ns(), mode='recording', error=None)
                        self.status[channel + '_connection'] = 'connected'
                        delay = 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                reason = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
                self.status.update(error=reason)
                self.status[channel + '_connection'] = 'reconnecting'
                self.append('gap', {'reason': reason, 'stream': channel})
                self.store.commit()
                if reason.endswith('_reached'):
                    raise
                await asyncio.sleep(delay)
                delay = min(60, delay*2)

    async def heartbeat(self):
        while True:
            self.append('heartbeat', {'mode': self.status['mode']})
            self.store.commit()
            await asyncio.sleep(10)

    async def run(self):
        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(self.discover())
                group.create_task(self.resolve())
                group.create_task(self.stream('benchmark'))
                group.create_task(self.stream('book'))
                group.create_task(self.heartbeat())
        finally:
            self.status['mode'] = 'stopped'
            await self.client.close()
            self.store.close()
