"""Intentionally artificial data to exercise plumbing, never a trading backtest."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from .storage import Store


def market_fixture(start=1800000000, name='SYNTHETIC', **overrides):
    def iso(sec):
        return datetime.fromtimestamp(sec, timezone.utc).isoformat()
    return {'ticker': 'KXBTC15M-' + name, 'event_ticker': 'KXBTC15M-EVENT-' + name, 'floor_strike': 80000,
            'custom_strike': {'round_digits': '2'},
            'strike_type': 'greater_or_equal', 'open_time': iso(start), 'close_time': iso(start + 900),
            'rules_primary': 'SYNTHETIC: average of BRTI during the final sixty seconds',
            'status': 'active', 'result': '', **overrides}


def index_frame(sec, price):
    return {'type': 'cfbenchmarks_value', 'msg': {'index_id': 'BRTI',
            'data': json.dumps({'time': sec * 1000, 'value': str(price)})}}


def book_frame(ticker, seq, yes_ask='.30', yes_bid='.28', quantity='10'):
    return {'type': 'orderbook_snapshot', 'sid': 1, 'seq': seq, 'msg': {
        'market_ticker': ticker, 'yes_dollars_fp': [[yes_bid, quantity]],
        # With use_yes_price, the NO bid is represented at its YES complement.
        'no_dollars_fp': [[yes_ask, quantity]],
    }}


def create_demo(path: Path, markets=10):
    if path.exists():
        raise ValueError('Refusing to overwrite an existing data store')
    store = Store(path)
    try:
        start = 1800000000
        store.append('series', {'synthetic': True, 'series': {'ticker': 'KXBTC15M',
                     'fee_type': 'quadratic', 'fee_multiplier': 1}}, received_ns=(start-1) * 10**9)
        seq = 0
        for n in range(markets):
            begin = start + n * 901
            market = market_fixture(begin, f'SYNTHETIC-{n:03d}')
            store.append('market', {'market': market, 'synthetic': True}, received_ns=begin * 10**9)
            for offset in range(901):
                sec = begin + offset
                # Alternating toy oscillations deliberately yield grossly mispriced toy quotes.
                price = 80000 + 2 * math.sin(offset * .9)
                if offset % 60 == 0:
                    store.append('event_metadata', {'synthetic': True, 'event': {
                        'event_ticker': market['event_ticker'], 'series_ticker': 'KXBTC15M'}},
                        received_ns=sec * 10**9)
                if offset == 0:
                    store.append('series', {'synthetic': True, 'series': {'ticker': 'KXBTC15M',
                        'fee_type': 'quadratic', 'fee_multiplier': 1}}, received_ns=sec * 10**9)
                seq += 1
                for frame, lag in ((index_frame(sec, price), 10_000_000),
                                   (book_frame(market['ticker'], seq), 20_000_000)):
                    store.append('ws', {'frame': frame, 'session': f'demo-{n}',
                                       'book_convention': 'yes_price', 'synthetic': True},
                                 received_ns=sec * 10**9 + lag, source_ns=sec * 10**9)
            store.append('market', {'market': {**market, 'result': 'yes' if n % 2 else 'no',
                                               'status': 'finalized'}, 'synthetic': True},
                         received_ns=(begin + 900) * 10**9 + 30_000_000)
        store.commit()
    finally:
        store.close()
