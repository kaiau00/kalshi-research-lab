from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from pathlib import Path

import httpx

from .market import epoch_ns
from .recorder import SERIES, MarketDataClient
from .research import write_json
from .storage import Store


async def download(path: Path, days=2, max_markets=192):
    if not 1 <= days <= 30 or not 1 <= max_markets <= 2880:
        raise ValueError('Bounded downloads: 1–30 days and 1–2880 markets')
    if path.exists():
        raise ValueError('Use a new historical dataset path to preserve download provenance')
    store, client = Store(path), MarketDataClient()
    start, end = int(time.time()) - days * 86400, int(time.time())
    found, downloaded, errors = {}, 0, []
    try:
        # Recent and archived listings can overlap. Deduplicate by exact market ticker.
        for endpoint in ('/markets', '/historical/markets'):
            cursor = None
            for _ in range(30):
                params = {'series_ticker': SERIES, 'min_close_ts': start,
                          'max_close_ts': end, 'limit': 200}
                if cursor:
                    params['cursor'] = cursor
                try:
                    result = await client.get(endpoint, params)
                except httpx.HTTPStatusError as exc:
                    errors.append({'endpoint': endpoint, 'http_status': exc.response.status_code})
                    break
                store.append('historical_listing', {'endpoint': endpoint, 'params': params, 'response': result})
                for m in result.get('markets', []):
                    if (m['ticker'].startswith(SERIES + '-') and m.get('result') in ('yes', 'no')
                            and start <= epoch_ns(m['close_time']) / 1e9 <= end):
                        found[m['ticker']] = m
                cursor = result.get('cursor')
                if not cursor or len(found) >= max_markets:
                    break
        selected = sorted(found.values(), key=lambda m: m['close_time'], reverse=True)[:max_markets]
        for m in selected:
            ticker = m['ticker']
            store.append('historical_market', {'market': m})
            params = {'start_ts': int(epoch_ns(m['open_time']) / 1e9),
                      'end_ts': int(epoch_ns(m['close_time']) / 1e9), 'period_interval': 1}
            result = None
            for endpoint in (f'/series/{SERIES}/markets/{ticker}/candlesticks',
                             f'/historical/markets/{ticker}/candlesticks'):
                try:
                    result = await client.get(endpoint, params)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 404:
                        continue
                    errors.append({'ticker': ticker, 'http_status': exc.response.status_code})
                    break
                if result.get('candlesticks'):
                    break
            if result and result.get('candlesticks'):
                store.append('historical_candles', {'ticker': ticker, 'endpoint': endpoint,
                                                  'params': params, 'response': result})
                downloaded += 1
            else:
                errors.append({'ticker': ticker, 'reason': 'no_candles'})
            store.commit()
            await asyncio.sleep(.15)
        summary = {'requested_days': days, 'start_ts': start, 'end_ts': end, 'selected_markets': len(selected),
                   'markets_with_candles': downloaded, 'errors': errors, 'prefix': store.prefix(),
                   'use': 'Quote/outcome screening only; candles are not executable order-book replay data.'}
        write_json(path.with_suffix('.download.json'), summary)
        return summary
    finally:
        store.close()
        await client.close()


def screen(path, output):
    store = Store(path, readonly=True)
    try:
        integrity = store.verify()
        markets, candles = {}, {}
        for e in store.events():
            if e.kind == 'historical_market':
                markets[e.payload['market']['ticker']] = e.payload['market']
            elif e.kind == 'historical_candles':
                candles[e.payload['ticker']] = e.payload['response']['candlesticks']
        rows, missing = [], 0
        for ticker, market in markets.items():
            close = int(epoch_ns(market['close_time']) / 1e9)
            for horizon in (60, 120, 300):
                # Require the exact completed candle boundary; don't reach forward or fill gaps.
                candle = next((c for c in candles.get(ticker, [])
                               if c['end_period_ts'] == close - horizon), None)
                try:
                    bid = Decimal(candle['yes_bid']['close_dollars'])
                    ask = Decimal(candle['yes_ask']['close_dollars'])
                    if not bid.is_finite() or not ask.is_finite() or not 0 < bid < ask < 1:
                        raise ValueError('Invalid quote')
                except (KeyError, TypeError, ValueError, ArithmeticError):
                    missing += 1
                    continue
                yes = market['result'] == 'yes'
                midpoint = float((bid + ask) / 2)
                side = 'yes' if ask < 1 - bid else 'no'
                rows.append({'ticker': ticker, 'seconds_left': horizon, 'yes_midpoint': midpoint,
                             'yes_result': yes, 'quoted_underdog': side,
                             'underdog_ask': float(ask if side == 'yes' else 1 - bid),
                             'underdog_won': yes if side == 'yes' else not yes,
                             'squared_probability_error': (midpoint - yes) ** 2})
        bands = []
        for horizon in (60, 120, 300):
            for lo, hi in ((0, .1), (.1, .2), (.2, .35), (.35, .5)):
                sample = [r for r in rows if r['seconds_left'] == horizon and lo <= r['underdog_ask'] < hi]
                if sample:
                    bands.append({'seconds_left': horizon, 'underdog_price_band': [lo, hi], 'n': len(sample),
                                  'mean_quoted_ask': sum(r['underdog_ask'] for r in sample) / len(sample),
                                  'observed_win_rate': sum(r['underdog_won'] for r in sample) / len(sample)})
        report = {'label': 'HISTORICAL QUOTE SCREEN — NOT A FILL OR RETURN BACKTEST',
                  'integrity': integrity, 'unique_markets': len(markets), 'missing_samples': missing,
                  'assumptions': ['Minute closing quotes have no executable depth or within-minute path.',
                                  'Rows at different horizons are correlated; count unique markets, not rows.',
                                  'No historical BRTI stream is included, so distance-to-strike filters cannot be tested.',
                                  'Comparing win rates with quotes excludes fees, fills, and capital constraints.'],
                  'bands': bands, 'observations': rows}
        write_json(output, report)
        return report
    finally:
        store.close()
