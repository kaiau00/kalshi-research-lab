import asyncio

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
