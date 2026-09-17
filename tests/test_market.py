import math
from decimal import Decimal

import pytest

from research_lab.demo import book_frame, index_frame, market_fixture
from research_lab.market import MarketState
from research_lab.settings import Experiment
from research_lab.storage import Event

START = 1800000000
NS = 10**9


def ws(frame, sec, **extra):
    return Event(1, int(sec * NS), None, 'ws', {'frame': frame, 'session': 'test',
                  'book_convention': 'yes_price', **extra})


def warmed_state(last=750):
    state = MarketState()
    state.series = {'ticker': 'KXBTC15M', 'fee_type': 'quadratic', 'fee_multiplier': 1}
    market = market_fixture()
    state.apply(Event(1, START * NS, None, 'market', {'market': market}))
    for offset in range(last - 120, last + 1):
        state.apply(ws(index_frame(START + offset, 80000 + math.sin(offset)), START + offset + .01))
    return state, market['ticker']


def test_price_scale_and_sequence_gap_require_new_snapshot():
    state, ticker = warmed_state()
    state.apply(ws(book_frame(ticker, 1, '.40', '.38'), START + 750))
    book = state.books[ticker]
    assert book.best_ask('yes') == Decimal('.40')
    assert book.best_ask('no') == Decimal('.62')
    assert book.no == {Decimal('.60'): Decimal(10)}
    frame = {'type': 'orderbook_delta', 'sid': 1, 'seq': 3, 'msg': {
        'market_ticker': ticker, 'side': 'no', 'price_dollars': '.40', 'delta_fp': '-1'}}
    state.apply(ws(frame, START + 751))
    assert not book.valid
    assert state.quality['gaps'] == 1
    frame['seq'] = 4
    state.apply(ws(frame, START + 752))
    assert not book.valid
    state.apply(ws(book_frame(ticker, 5), START + 753))
    assert book.valid


def test_duplicate_index_and_stale_inputs_do_not_create_forecasts():
    state, ticker = warmed_state()
    state.apply(ws(index_frame(START + 750, 90000), START + 751))
    assert state.index[-1][1] < 80002
    assert state.forecast(ticker, (START + 751) * NS, Experiment()) is not None
    assert state.forecast(ticker, (START + 755) * NS, Experiment()) is None
    del state.markets[ticker]['floor_strike']
    assert state.metadata(ticker) is None


def test_settlement_average_uses_accumulated_seconds_and_rejects_a_gap():
    state, ticker = warmed_state(870)
    fair = state.forecast(ticker, int((START + 870.1) * NS), Experiment())
    assert fair['observed_settlement_seconds'] == 31  # seconds 840 through 870
    observed = [p for sec, p, _ in state.index if START + 840 <= sec <= START + 870]
    expected = (sum(observed) + 29 * state.index[-1][1]) / 60
    assert fair['expected_average'] == pytest.approx(expected)
    state.index = type(state.index)((row for row in state.index if row[0] != START + 850), maxlen=7200)
    assert state.forecast(ticker, int((START + 870.1) * NS), Experiment()) is None


@pytest.mark.parametrize('change', ['unknown_convention', 'negative_depth', 'crossed'])
def test_bad_book_fails_closed(change):
    state, ticker = warmed_state()
    frame = book_frame(ticker, 1)
    extra = {}
    if change == 'unknown_convention':
        extra['book_convention'] = 'legacy'
    if change == 'negative_depth':
        frame['msg']['yes_dollars_fp'][0][1] = '-1'
    if change == 'crossed':
        frame['msg']['yes_dollars_fp'][0][0] = '.50'
    state.apply(ws(frame, START + 751, **extra))
    assert not state.books[ticker].valid


@pytest.mark.parametrize('remaining_side', [None, 'yes', 'no'])
def test_snapshot_omitted_sides_clear_old_depth(remaining_side):
    state, ticker = warmed_state()
    state.apply(ws(book_frame(ticker, 1), START + 751))
    frame = book_frame(ticker, 2)
    for side in ('yes', 'no'):
        if side != remaining_side:
            del frame['msg'][side + '_dollars_fp']
    state.apply(ws(frame, START + 752))
    book = state.books[ticker]
    assert book.valid
    assert state.quality['malformed'] == 0
    for side in ('yes', 'no'):
        assert bool(getattr(book, side)) == (side == remaining_side)
    if remaining_side is None:
        assert book.best_ask('yes') is None
        assert book.best_ask('no') is None
    # A later snapshot restores executable quotes without an invented sequence gap.
    state.apply(ws(book_frame(ticker, 3), START + 753))
    assert book.valid and book.best_ask('yes') is not None and book.best_ask('no') is not None
    assert state.quality['gaps'] == 0


@pytest.mark.parametrize('levels', [None, {}, '', 0])
def test_present_malformed_snapshot_side_still_fails_closed(levels):
    state, ticker = warmed_state()
    frame = book_frame(ticker, 1)
    frame['msg']['yes_dollars_fp'] = levels
    state.apply(ws(frame, START + 751))
    assert state.quality['malformed'] == 1
    assert not state.books[ticker].valid


def test_settlement_forecast_includes_first_second_before_close():
    state, ticker = warmed_state(840)
    fair = state.forecast(ticker, int((START + 840.1) * NS), Experiment())
    assert fair['observed_settlement_seconds'] == 1
    # Missing the first settlement second must block later forecasts.
    state, ticker = warmed_state(870)
    state.index = type(state.index)((row for row in state.index if row[0] != START + 840), maxlen=7200)
    assert state.forecast(ticker, int((START + 870.1) * NS), Experiment()) is None


def test_subscription_ack_consumes_sequence_without_invalidating_book():
    state, ticker = warmed_state()
    state.apply(ws(book_frame(ticker, 1), START + 751))
    state.apply(ws({'type': 'ok', 'sid': 1, 'seq': 2, 'msg': {'market_tickers': [ticker]}}, START + 752))
    state.apply(ws({'type': 'orderbook_delta', 'sid': 1, 'seq': 3, 'msg': {
        'market_ticker': ticker, 'side': 'yes', 'price_dollars': '.28', 'delta_fp': '1'}}, START + 753))
    assert state.books[ticker].valid
    assert state.quality['gaps'] == 0
