from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import time
import uuid
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from research_lab.engine import STRATEGIES, Replay, entry_fee
from research_lab.market import Book
from research_lab.research import source_hash
from research_lab.settings import Experiment
from research_lab.storage import Store

from .client import WS, DemoClient
from .journal import Journal, dumps

RISK_PER_MARKET = Decimal('3.00')
CONFIG_REVISION = 'risk-cap-3-20260924'
DEFAULT_STRATEGY = 'basic_fair_value'
DEFAULT_STARTING_CASH = Decimal('125.00')


def parse_book(data, received_ns):
    # REST uses each outcome's own bid price. The research WebSocket explicitly
    # requests YES-price coordinates; do not apply that conversion to REST.
    raw = data['orderbook_fp']
    levels = {}
    for side in ('yes', 'no'):
        levels[side] = {}
        for p, q in raw[side + '_dollars']:
            price, quantity = Decimal(p), Decimal(q)
            if (not price.is_finite() or not quantity.is_finite()
                    or not 0 < price < 1 or quantity < 0 or price in levels[side]):
                raise ValueError('Invalid demo book')
            if quantity:
                levels[side][price] = quantity
    valid = bool(levels['yes'] and levels['no'] and max(levels['yes']) + max(levels['no']) < 1)
    return Book(levels['yes'], levels['no'], received_ns, valid)


def order_payload(decision, max_order_cost=Decimal('1.00')):
    price = decision['limit']
    quantity = decision['quantity']
    # Reserve a cent-rounded fee per contract, conservatively covering the
    # simulator's aggregate fee assumption. Exchange fills determine actual cost.
    unit = (price + entry_fee(price, 1, Experiment())).quantize(Decimal('.01'), rounding=ROUND_CEILING)
    quantity = min(quantity, int(Decimal(max_order_cost) / unit))
    if quantity < 1:
        return None
    return {'ticker': decision['ticker'], 'client_order_id': 'fv-' + uuid.uuid4().hex,
            'side': 'bid' if decision['side'] == 'yes' else 'ask',
            'price': str(price if decision['side'] == 'yes' else 1-price),
            'count': str(quantity), 'time_in_force': 'immediate_or_cancel',
            'self_trade_prevention_type': 'taker_at_cross', 'exchange_index': 2, 'subaccount': 0}


class Runner:
    def __init__(self, root=None):
        self.strategy = os.environ.get('LAB_DEMO_STRATEGY', DEFAULT_STRATEGY)
        if self.strategy not in STRATEGIES:
            raise ValueError('Unsupported demo strategy')
        try:
            self.starting_cash = Decimal(os.environ.get('LAB_DEMO_STARTING_CASH',
                                                        str(DEFAULT_STARTING_CASH)))
        except Exception as exc:
            raise ValueError('Invalid demo starting cash') from exc
        if not self.starting_cash.is_finite() or self.starting_cash < RISK_PER_MARKET:
            raise ValueError('Invalid demo starting cash')
        self.root = Path(root or os.environ.get('LAB_DEMO_DIR', '/data/demo-fair-value-001'))
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = (self.root / 'runner.lock').open('a')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.cfg = Experiment(bankroll=str(self.starting_cash), risk_per_market=str(RISK_PER_MARKET))
        self.client = DemoClient(max_order_cost=RISK_PER_MARKET)
        self.journal = Journal(self.root / 'orders.sqlite3', max_order_cost=RISK_PER_MARKET)
        identity = hashlib.sha256(self.client.key_id.encode()).hexdigest()
        self.journal.register(self.cfg.to_dict(), identity, strategy=self.strategy,
                              revision=CONFIG_REVISION)
        self.raw = Store(self.root / 'events.sqlite3')
        self.replay = Replay(self.cfg)
        self.state = self.replay.state
        self.status = {'environment': 'demo', 'strategy': self.strategy, 'state': 'starting',
                       'bankroll': str(self.starting_cash), 'risk_per_market': str(RISK_PER_MARKET),
                       'config_revision': CONFIG_REVISION, 'exchange_index': 2,
                       'execution': 'exchange IOC; measured network latency, no simulated fills',
                       'strategy_parameters': self.strategy_parameters(),
                       'started_ns': time.time_ns()}
        self.current = []
        self.discovery_at = self.series_at = 0
        self.event_at = {}
        self.snapshot_at = 0
        self.account_at = 0
        self.settlement_at = 0
        demo_hash = hashlib.sha256(b''.join(p.read_bytes() for p in sorted(Path(__file__).parent.glob('*.py'))))
        self.record('demo_start', {'config': self.cfg.to_dict(), 'strategy': self.strategy,
                                  'research_source': source_hash(),
                                  'demo_source': demo_hash.hexdigest(), 'environment': 'demo'})

    def strategy_parameters(self):
        parameters = {'min_seconds_left': self.cfg.min_seconds_left,
                      'max_seconds_left': self.cfg.max_seconds_left,
                      'min_net_edge': self.cfg.min_edge}
        if self.strategy == 'tail_underdog':
            parameters.update(tail_max_seconds=self.cfg.tail_max_seconds,
                              tail_max_price=self.cfg.tail_max_price,
                              tail_max_abs_z=self.cfg.tail_max_z,
                              side_selection='cheaper_outcome_only')
        elif self.strategy == 'adaptive_volatility':
            parameters.update(fast_window_seconds=self.cfg.fast_window_seconds,
                              slow_window_seconds=self.cfg.slow_window_seconds)
        return parameters

    def record(self, kind, payload):
        event = self.raw.append(kind, payload)
        self.raw.commit()
        self.state.apply(event)
        if self.raw.stats()['bytes'] > 256_000_000:
            raise RuntimeError('Demo recording capacity reached; preserved data, stopped new orders')
        return event

    async def read(self, path, params=None):
        started = time.time_ns()
        data = await self.client.get(path, params)
        self.record('demo_rest', {'path': path, 'params': params, 'request_ns': started, 'response': data})
        return data, started

    async def benchmark(self):
        while True:
            session = uuid.uuid4().hex
            self.record('gap', {'stream': 'benchmark', 'reason': 'demo_connection'})
            try:
                async with connect(WS, additional_headers=self.client.headers('GET', '/trade-api/ws/v2'),
                                   ping_interval=15, ping_timeout=15, max_queue=32) as ws:
                    await ws.send(dumps({'id': 1, 'cmd': 'subscribe',
                                         'params': {'channels': ['cfbenchmarks_value'], 'index_ids': ['BRTI']}}))
                    while True:
                        frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                        if frame.get('type') == 'error':
                            raise ValueError('Demo benchmark subscription rejected')
                        self.record('ws', {'frame': frame, 'session': session, 'book_convention': 'yes_price'})
                        if frame.get('type') == 'cfbenchmarks_value':
                            self.status['benchmark_received_ns'] = time.time_ns()
            except (httpx.HTTPError, OSError, TimeoutError, ValueError, ConnectionClosed, InvalidStatus) as exc:
                self.status['benchmark_error'] = type(exc).__name__
                self.record('gap', {'stream': 'benchmark', 'reason': type(exc).__name__})
                await asyncio.sleep(5)

    async def discover(self):
        now = time.time()
        if now - self.discovery_at < 5:
            return
        data, _ = await self.read('/markets', {'series_ticker': 'KXBTC15M', 'min_close_ts': int(now),
                                             'max_close_ts': int(now) + 1800, 'limit': 100})
        if data.get('cursor'):
            raise RuntimeError('Unexpected demo discovery pagination')
        self.current = []
        for market in data['markets']:
            if market.get('exchange_index') != 2:
                continue
            self.record('market', {'market': market})
            if market.get('status') == 'active':
                self.current.append(market['ticker'])
        self.discovery_at = now
        if now - self.series_at > 600:
            data, _ = await self.read('/series/KXBTC15M')
            self.record('series', data)
            self.series_at = now
        for ticker in self.current:
            event = self.state.markets[ticker]['event_ticker']
            if now - self.event_at.get(event, 0) > 45:
                data, _ = await self.read('/events/' + event)
                self.record('event_metadata', {'event': data['event']})
                self.event_at[event] = now
        # Retain only recent model metadata; full responses remain in the raw log.
        self.state.markets = {t: m for t, m in self.state.markets.items() if t in self.current}
        self.state.books = {t: b for t, b in self.state.books.items() if t in self.current}
        events = {m['event_ticker'] for m in self.state.markets.values()}
        self.state.event_fees = {k: v for k, v in self.state.event_fees.items() if k in events}
        self.event_at = {k: v for k, v in self.event_at.items() if k in events}

    async def book(self, ticker):
        data, started = await self.read('/markets/' + ticker + '/orderbook', {'depth': 1})
        # Using request start conservatively includes REST round-trip delay in quote age.
        self.state.books[ticker] = parse_book(data, started)

    def signal(self, ticker, cash):
        model = Replay(self.cfg)
        model.state = self.state
        account = model.accounts[self.strategy]
        account.cash = min(self.starting_cash, cash)
        rows = self.journal.rows(ticker)
        account.attempts[ticker] = len(rows)
        if rows:
            account.last_attempt[ticker] = rows[-1]['created_ns']
        if any(r['exchange_order'] and Decimal(json.loads(r['exchange_order'])['fill_count_fp']) > 0
               for r in rows):
            account.traded.add(ticker)
        model._decide(account, ticker, time.time_ns())
        self.status['last_rejections'] = account.rejected
        return account.pending.get(ticker)

    async def reconcile(self):
        for row in self.journal.pending():
            cursor = ''
            found = None
            for _ in range(10):
                data, _ = await self.read('/portfolio/orders', {'ticker': row['ticker'], 'exchange_index': 2,
                                                               'limit': 200, 'cursor': cursor})
                matches = [o for o in data['orders'] if o['client_order_id'] == row['client_id']]
                if matches:
                    if len(matches) != 1:
                        raise RuntimeError('Duplicate demo client order ID')
                    found = matches[0]
                    break
                cursor = data.get('cursor', '')
                if not cursor:
                    break
            if found:
                self.journal.reconcile(row['client_id'], found)
            # A missing response is never interpreted as proof the POST failed.
        return not self.journal.pending()

    async def account(self):
        balance, _ = await self.read('/portfolio/balance', {'exchange_index': 2})
        cash = Decimal(balance['balance_dollars'])
        if not cash.is_finite() or cash < 0:
            raise RuntimeError('Invalid demo balance')
        self.status['cash'] = str(cash)
        self.status['portfolio_value_cents'] = balance.get('portfolio_value')
        self.status['balance_observed_ns'] = time.time_ns()
        return cash

    async def settlements(self):
        if time.time() - self.settlement_at < 30:
            return
        done = {s['ticker'] for s in self.journal.settled()}
        for row in self.journal.rows():
            ticker = row['ticker']
            if ticker in done or not row['exchange_order']:
                continue
            if Decimal(json.loads(row['exchange_order'])['fill_count_fp']) <= 0:
                continue
            data, _ = await self.read('/portfolio/settlements', {'ticker': ticker, 'limit': 100})
            if data.get('cursor'):
                raise RuntimeError('Unexpected demo settlement pagination')
            matches = [s for s in data['settlements'] if s['ticker'] == ticker and s['exchange_index'] == 2]
            if len(matches) > 1:
                raise RuntimeError('Multiple demo settlements for one ticker')
            if matches:
                self.journal.settlement(ticker, matches[0])
        self.settlement_at = time.time()

    async def step(self):
        await self.discover()
        await self.settlements()
        if not await self.reconcile():
            self.status['state'] = 'blocked_unconfirmed_order'
            return
        if time.time() - self.account_at > 15:
            await self.account()
            self.account_at = time.time()
        if not self.journal.rows() and Decimal(self.status.get('cash', '0')) != Decimal(self.cfg.bankroll):
            self.status['state'] = 'waiting_initial_demo_funding'
            self.status['markets'] = self.current
            return
        self.status['state'] = 'watching'
        self.status['markets'] = self.current
        for ticker in self.current:
            meta = self.state.metadata(ticker)
            max_seconds = (self.cfg.tail_max_seconds if self.strategy == 'tail_underdog'
                           else self.cfg.max_seconds_left)
            if not meta or not self.cfg.min_seconds_left <= (meta[2] - time.time_ns()) / 1e9 <= max_seconds:
                continue
            await self.book(ticker)
            if not self.signal(ticker, Decimal(self.status.get('cash', '0'))):
                continue
            exchange, _ = await self.read('/exchange/status')
            shards = [x for x in exchange.get('exchange_index_statuses', []) if x['exchange_index'] == 2]
            if (not exchange.get('trading_active') or not exchange.get('exchange_active') or len(shards) != 1
                    or not shards[0].get('trading_active') or not shards[0].get('exchange_active')):
                self.status['state'] = 'exchange_paused'
                continue
            cash = await self.account()
            positions, _ = await self.read('/portfolio/positions', {'ticker': ticker, 'exchange_index': 2})
            resting, _ = await self.read('/portfolio/orders', {'status': 'resting', 'exchange_index': 2})
            if (positions.get('cursor') or resting.get('cursor') or resting['orders']
                    or any(Decimal(p['position_fp']) != 0 for p in positions['market_positions'])):
                self.status['state'] = 'existing_account_exposure'
                continue
            # Refresh quotes after account reads; never send the earlier signal on a stale book.
            await self.book(ticker)
            decision = self.signal(ticker, cash)
            if decision is None:
                continue
            payload = order_payload(decision, RISK_PER_MARKET)
            if payload is None:
                continue
            self.journal.intent(payload, decision)
            self.record('demo_order_intent', {'payload': payload, 'decision': json.loads(dumps(decision))})
            started = time.time_ns()
            try:
                response = await self.client.submit(payload)
                self.record('demo_order_ack', {'client_id': payload['client_order_id'], 'response': response,
                                               'request_ns': started, 'elapsed_ms': (time.time_ns()-started)/1e6})
            except httpx.HTTPStatusError as exc:
                definitive = exc.response.status_code in (400, 401, 403, 422, 429)
                self.journal.error(payload['client_order_id'], 'HTTP_' + str(exc.response.status_code),
                                   definitive=definitive)
                if exc.response.status_code in (401, 403):
                    raise RuntimeError('Demo credential lacks order permission') from None
            except httpx.RequestError as exc:
                self.journal.error(payload['client_order_id'], type(exc).__name__)
            await self.reconcile()

    def snapshot(self):
        rows = self.journal.rows()
        orders = [json.loads(r['exchange_order']) for r in rows if r['exchange_order']]
        settled = self.journal.settled()
        self.status.update(updated_ns=time.time_ns(), submitted_attempts=len(rows),
                           settled_markets=len(settled),
                           realized_net_pnl=str(sum((Decimal(s['pnl']) for s in settled), Decimal(0))),
                           filled_markets=sum(Decimal(o['fill_count_fp']) > 0 for o in orders),
                           unresolved_orders=len(self.journal.pending()),
                           recent_orders=[{'ticker': r['ticker'], 'state': r['state'], 'error': r['error'],
                                           'order': json.loads(r['exchange_order']) if r['exchange_order'] else None}
                                          for r in rows[-10:]])
        path = self.root / 'status.tmp'
        path.write_text(dumps(self.status))
        os.replace(path, self.root / 'status.json')

    async def loop(self):
        while True:
            if (self.root / 'STOP').exists():
                self.status['state'] = 'stopped_by_file'
            else:
                try:
                    await self.step()
                    self.status.pop('error', None)
                except (httpx.HTTPError, TimeoutError) as exc:
                    self.status.update(state='waiting_api', error=type(exc).__name__)
            self.snapshot()
            await asyncio.sleep(1)

    async def run(self):
        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(self.benchmark())
                group.create_task(self.loop())
        except Exception as exc:
            errors = list(exc.exceptions) if isinstance(exc, ExceptionGroup) else [exc]
            reasons = [str(e) if isinstance(e, RuntimeError) else type(e).__name__ for e in errors]
            self.status.update(state='stopped_error', error='; '.join(reasons))
            self.snapshot()
            raise
        finally:
            await self.client.close()
            self.raw.close()
            self.journal.db.close()
            self.lock.close()
