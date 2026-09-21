import asyncio

import pytest

from research_lab.demo import market_fixture
from research_lab.market import MarketState
from research_lab.recorder import Recorder
from research_lab.storage import Event


def test_determined_outcome_stays_pending_until_finalized(tmp_path, monkeypatch):
    monkeypatch.delenv('LAB_SEGMENTED', raising=False)
    r = Recorder(tmp_path / 'events.db')
    market = market_fixture(status='determined', result='yes')
    r.remember(market)
    assert market['ticker'] in r.pending
    r.remember({**market, 'status': 'finalized'})
    assert market['ticker'] not in r.pending
    r.remember({**market, 'status': 'finalized', 'result': 'no'})
    assert any(e.kind == 'outcome_revision' for e in r.store.events())
    r.store.close()
    asyncio.run(r.client.close())


def test_book_rollover_does_not_clear_benchmark_history():
    state = MarketState()
    state.index.append((100, 80000, 100000000000))
    state.last_index_source = 100
    state.apply(Event(1, 100000000001, None, 'gap', {'stream': 'book'}))
    assert len(state.index) == 1
    state.apply(Event(2, 100000000002, None, 'gap', {'stream': 'benchmark'}))
    assert not state.index and state.last_index_source == -1


@pytest.mark.parametrize("uptime", [0.0, 10.0, 10000.0])
def test_event_fee_capture_and_refresh_throttle(tmp_path, monkeypatch, uptime):
    monkeypatch.delenv('LAB_SEGMENTED', raising=False)
    r = Recorder(tmp_path / 'events.db')
    m = market_fixture()
    r.remember(m)
    r.watch = {m['ticker']}
    calls = []

    async def get(path):
        calls.append(path)
        return {'event': {'event_ticker': m['event_ticker'], 'series_ticker': 'KXBTC15M',
                          'fee_multiplier_override': 2}}

    r.client.get = get
    monkeypatch.setattr('research_lab.recorder.time.monotonic', lambda: uptime)
    asyncio.run(r.refresh_event_fees())
    asyncio.run(r.refresh_event_fees())
    assert calls == ['/events/' + m['event_ticker']]
    records = [e for e in r.store.events() if e.kind == 'event_metadata']
    assert len(records) == 1 and records[0].payload['event']['fee_multiplier_override'] == 2
    r.store.close()
    asyncio.run(r.client.close())


def test_series_requested_immediately_at_zero_uptime(tmp_path, monkeypatch):
    monkeypatch.delenv('LAB_SEGMENTED', raising=False)
    r = Recorder(tmp_path / 'events.db')
    calls = []

    async def get(path):
        calls.append(path)
        raise asyncio.CancelledError()

    r.client.get = get
    monkeypatch.setattr('research_lab.recorder.time.monotonic', lambda: 0.0)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(r.resolve())
    assert calls == ['/series/KXBTC15M']
    r.store.close()
    asyncio.run(r.client.close())
