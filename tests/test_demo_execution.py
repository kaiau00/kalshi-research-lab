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
from demo_execution.client import BASE, DemoClient, validate_order
from demo_execution.journal import Journal
from demo_execution.runner import Runner, order_payload, parse_book


def pem():
    return ed25519.Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def intent(side='no'):
    return order_payload({'ticker': 'KXBTC15M-26SEP232215-15', 'limit': Decimal('.38'),
                          'quantity': 2, 'side': side})


def result(p, fill='1.50'):
    return {'client_order_id': p['client_order_id'], 'ticker': p['ticker'], 'exchange_index': 2,
            'outcome_side': 'yes' if p['side'] == 'bid' else 'no', 'subaccount_number': 0,
            'fill_count_fp': fill, 'remaining_count_fp': '0.00', 'status': 'canceled',
            'taker_fill_cost_dollars': '.5700', 'maker_fill_cost_dollars': '0',
            'taker_fees_dollars': '.0248', 'maker_fees_dollars': '0'}


def test_no_side_and_rest_book_have_distinct_price_coordinates():
    p = intent()
    assert p['side'] == 'ask' and Decimal(p['price']) == Decimal('.62')
    book = parse_book({'orderbook_fp': {'yes_dollars': [['.60', '5']], 'no_dollars': [['.35', '4']]}}, 123)
    assert book.best_ask('no') == Decimal('.40')
    assert book.best_ask('yes') == Decimal('.65')
    assert book.at_ns == 123 and book.valid
    assert not parse_book({'orderbook_fp': {'yes_dollars': [['.65', '5']],
                                          'no_dollars': [['.35', '4']]}}, 123).valid


@pytest.mark.parametrize('price', ['.0001', '.058', '.38', '.50', '.80', '.99', '.9999'])
def test_sizing_retains_one_dollar_limit_with_conservative_fee_reserve(price):
    from research_lab.engine import entry_fee
    from research_lab.settings import Experiment
    price = Decimal(price)
    p = order_payload({'ticker': 'KXBTC15M-26SEP232215-15', 'limit': price,
                       'quantity': int(1/price), 'side': 'no'})
    if p:
        validate_order(p)
        qty = int(p['count'])
        assert qty * price + entry_fee(price, qty, Experiment()) <= 1


def test_demo_request_signing_scope_and_no_retries():
    key = pem()
    calls = []
    def handle(req):
        calls.append(req)
        assert str(req.url).startswith(BASE + '/trade-api/v2/')
        msg = (req.headers['KALSHI-ACCESS-TIMESTAMP'] + req.method + req.url.path).encode()
        serialization.load_pem_private_key(key, None).public_key().verify(
            base64.b64decode(req.headers['KALSHI-ACCESS-SIGNATURE']), msg)
        return httpx.Response(503, json={'code': 'temporary'})
    async def check():
        c = DemoClient('demo-test', key, transport=httpx.MockTransport(handle))
        try:
            with pytest.raises(httpx.HTTPStatusError):
                await c.submit(intent())
            assert len(calls) == 1
            for path in ('https://external-api.kalshi.com/portfolio/orders', '/../portfolio/balance',
                         '/portfolio/intra_exchange_instance_transfer'):
                with pytest.raises(ValueError):
                    await c.get(path)
            assert len(calls) == 1
        finally:
            await c.close()
    asyncio.run(check())


@pytest.mark.parametrize('change', [{'exchange_index': 0}, {'time_in_force': 'good_till_canceled'},
                                    {'ticker': 'KXETH15M-X'}, {'count': '100'}, {'price': 'NaN'},
                                    {'subaccount': 1}])
def test_wrong_scope_or_budget_rejected(change):
    p = intent()
    p.update(change)
    with pytest.raises(ValueError):
        validate_order(p)


def test_uncertain_order_survives_restart_and_partial_fill_blocks_reentry(tmp_path):
    path = tmp_path / 'journal.sqlite3'
    j = Journal(path)
    p = intent()
    j.intent(p, {})
    j.error(p['client_order_id'], 'timeout')
    j.db.close()
    j = Journal(path)
    with pytest.raises(RuntimeError, match='Unreconciled'):
        j.intent(intent('yes'), {})
    j.reconcile(p['client_order_id'], result(p))
    assert not j.pending()
    with pytest.raises(RuntimeError, match='fill limit'):
        j.intent(intent('yes'), {})
    j.db.close()


@pytest.mark.parametrize('change', [{'ticker': 'wrong'}, {'remaining_count_fp': '1'},
                                    {'fill_count_fp': '3'}, {'outcome_side': 'yes'},
                                    {'taker_fees_dollars': '.99'}, {'exchange_index': 0}])
def test_mismatched_or_overbudget_response_stays_blocked(tmp_path, change):
    j = Journal(tmp_path / 'j.sqlite3')
    p = intent()
    j.intent(p, {})
    r = result(p)
    r.update(change)
    with pytest.raises(RuntimeError):
        j.reconcile(p['client_order_id'], r)
    assert len(j.pending()) == 1
    j.db.close()


def test_runner_uses_existing_fair_value_and_does_not_simulate_fills(tmp_path, monkeypatch):
    replay, ticker, account, now = prepared()
    monkeypatch.setenv('KALSHI_DEMO_KEY_ID', 'test')
    monkeypatch.setenv('KALSHI_DEMO_PRIVATE_KEY_B64', base64.b64encode(pem()).decode())
    r = Runner(tmp_path)
    try:
        r.state = replay.state
        monkeypatch.setattr('demo_execution.runner.time.time_ns', lambda: now)
        signal = r.signal(ticker, Decimal('125'))
        for field in ('side', 'limit', 'quantity', 'probability', 'edge'):
            assert signal[field] == account.pending[ticker][field]
        assert not r.journal.rows()
        r.state.books[ticker].at_ns = now - 3_000_000_000
        assert r.signal(ticker, Decimal('125')) is None
    finally:
        asyncio.run(r.client.close())
        r.raw.close()
        r.journal.db.close()
        r.lock.close()


def test_unknown_order_is_not_resubmitted(tmp_path, monkeypatch):
    monkeypatch.setenv('KALSHI_DEMO_KEY_ID', 'test')
    monkeypatch.setenv('KALSHI_DEMO_PRIVATE_KEY_B64', base64.b64encode(pem()).decode())
    r = Runner(tmp_path)
    r.journal.intent(intent(), {})
    calls = []
    async def read(path, params=None):
        calls.append(path)
        return {'orders': [], 'cursor': ''}, 0
    r.read = read
    try:
        assert not asyncio.run(r.reconcile())
        assert not asyncio.run(r.reconcile())
        assert calls == ['/portfolio/orders', '/portfolio/orders']
        assert len(r.journal.pending()) == 1
    finally:
        asyncio.run(r.client.close())
        r.raw.close()
        r.journal.db.close()
        r.lock.close()


def test_demo_status_protected_and_disabled_by_default(monkeypatch):
    monkeypatch.delenv('LAB_DEMO_ENABLED', raising=False)
    monkeypatch.setenv('LAB_DASHBOARD_PASSWORD', 'test-password-long-enough')
    with TestClient(create_app(record=False)) as c:
        assert c.get('/api/demo/status').status_code == 401
        result = c.get('/api/demo/status', auth=('lab', 'test-password-long-enough'))
        assert result.json()['state'] == 'disabled'
        assert c.get('/healthz').status_code == 200


def test_same_ledger_rejects_different_demo_account(tmp_path):
    j = Journal(tmp_path / 'j.sqlite3')
    j.register({'bankroll': '125'}, 'one')
    with pytest.raises(RuntimeError, match='registration changed'):
        j.register({'bankroll': '125'}, 'two')
    assert json.loads(j.db.execute('SELECT value FROM metadata').fetchone()[0])['identity'] == 'one'
    j.db.close()


def test_official_settlement_matches_fills_before_reporting_pnl(tmp_path):
    j = Journal(tmp_path / 'journal.sqlite3')
    p = intent()
    j.intent(p, {})
    j.reconcile(p['client_order_id'], result(p))
    s = {'ticker': p['ticker'], 'exchange_index': 2, 'yes_count_fp': '0', 'no_count_fp': '1.50',
         'yes_total_cost_dollars': '0', 'no_total_cost_dollars': '.57', 'fee_cost': '.0248',
         'revenue': 150}
    j.settlement(p['ticker'], s)
    assert Decimal(j.settled()[0]['pnl']) == Decimal('.9052')
    s['no_count_fp'] = '2.50'
    with pytest.raises(RuntimeError, match='settlement differs'):
        j.settlement(p['ticker'], s)
    j.db.close()


def test_full_step_journals_before_submit_and_never_reenters_after_fill(tmp_path, monkeypatch):
    replay, ticker, _, now = prepared()
    monkeypatch.setattr('demo_execution.runner.time.time_ns', lambda: now)
    monkeypatch.setenv('KALSHI_DEMO_KEY_ID', 'test')
    monkeypatch.setenv('KALSHI_DEMO_PRIVATE_KEY_B64', base64.b64encode(pem()).decode())
    r = Runner(tmp_path)
    r.state = replay.state
    r.current = [ticker]
    submitted = []
    async def noop():
        pass
    r.discover = r.settlements = noop
    async def read(path, params=None):
        responses = {
            '/portfolio/balance': {'balance_dollars': '125.00', 'portfolio_value': 0},
            '/portfolio/positions': {'market_positions': []},
            '/exchange/status': {'exchange_active': True, 'trading_active': True,
                                 'exchange_index_statuses': [{'exchange_index': 2,
                                    'exchange_active': True, 'trading_active': True}]},
            '/markets/' + ticker + '/orderbook': {'orderbook_fp': {
                'yes_dollars': [['.38', '10']], 'no_dollars': [['.60', '10']]}},
            '/portfolio/orders': {'orders': [result(submitted[-1])] if submitted else [], 'cursor': ''},
        }
        return responses[path], now
    async def submit(payload):
        assert len(r.journal.pending()) == 1
        assert r.journal.pending()[0]['client_id'] == payload['client_order_id']
        submitted.append(payload)
        return {'order_id': 'test-order', 'fill_count': '1.50'}
    r.read = read
    r.client.submit = submit
    async def exercise():
        await r.step()
        await r.step()
        assert len(submitted) == 1
        assert not r.journal.pending()
        await r.client.close()
    try:
        asyncio.run(exercise())
    finally:
        r.raw.close()
        r.journal.db.close()
        r.lock.close()


@pytest.mark.parametrize('cash', ['0', '100', '125.54'])
def test_first_order_waits_for_exact_authorized_initial_funding(tmp_path, monkeypatch, cash):
    monkeypatch.setenv('KALSHI_DEMO_KEY_ID', 'test')
    monkeypatch.setenv('KALSHI_DEMO_PRIVATE_KEY_B64', base64.b64encode(pem()).decode())
    r = Runner(tmp_path)

    async def noop():
        pass

    async def read(path, params=None):
        assert path == '/portfolio/balance'
        return {'balance_dollars': cash}, 0

    r.discover = r.settlements = noop
    r.read = read

    async def exercise():
        await r.step()
        assert r.status['state'] == 'waiting_initial_demo_funding'
        assert not r.journal.rows()
        await r.client.close()

    try:
        asyncio.run(exercise())
    finally:
        r.raw.close()
        r.journal.db.close()
        r.lock.close()
