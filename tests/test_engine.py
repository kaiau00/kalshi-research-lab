from decimal import Decimal

import pytest
from test_market import NS, START, warmed_state, ws

from research_lab.demo import book_frame
from research_lab.engine import Replay, entry_fee
from research_lab.settings import Experiment
from research_lab.storage import Event


def prepared(quantity='10'):
    replay = Replay(Experiment(latency_ms=500, risk_per_market='1.00'))
    replay.state, ticker = warmed_state()
    replay.state.apply(ws(book_frame(ticker, 1, '.40', '.38', quantity), START + 750))
    account = replay.accounts['basic_fair_value']
    now = int((START + 750.1) * NS)
    replay._decide(account, ticker, now)
    assert ticker in account.pending
    return replay, ticker, account, now


def test_limit_40_cents_cannot_fill_55_cents():
    replay, ticker, account, now = prepared()
    replay.state.apply(ws(book_frame(ticker, 2, '.55', '.53'), START + 751))
    replay._fill_due(account, (START + 751) * NS)
    assert account.orders[0]['status'] == 'canceled_limit_not_marketable'
    assert account.cash == 100
    assert account.reserved == 0
    assert not account.positions


def test_delayed_partial_fill_official_settlement_cash_and_fees():
    replay, ticker, account, now = prepared('1.5')
    replay._fill_due(account, now + 499_000_000)
    assert account.cash == 100 and account.reserved > 0
    replay._fill_due(account, now + 500_000_000)
    order = account.orders[0]
    assert order['status'] == 'partial_ioc' and order['filled'] == 1
    assert account.cash == Decimal('99.5832')
    assert account.reserved == 0
    replay._settle(account, (START + 901) * NS)
    assert ticker in account.positions  # No invented settlement from spot price.
    replay.state.markets[ticker]['result'] = 'yes'
    replay._settle(account, (START + 899) * NS)
    assert ticker in account.positions
    replay._settle(account, (START + 901) * NS)
    replay._settle(account, (START + 902) * NS)
    assert account.cash == Decimal('100.5832')
    assert len(account.closed) == 1
    assert account.closed[0]['pnl'] == Decimal('.5832')


@pytest.mark.parametrize('price', ['.001', '.099', '.40', '.99', '.999'])
def test_fee_rounding_and_total_budget(price):
    p = Decimal(price)
    cfg = Experiment()
    fee = entry_fee(p, 1, cfg)
    assert fee >= Decimal('.07') * p * (1 - p)
    assert (p + fee) % Decimal('.0001') == 0


def test_gap_cancels_delayed_order():
    replay, ticker, account, now = prepared()
    replay.feed(Event(10, now + NS, None, 'gap', {'reason': 'disconnect'}))
    assert account.orders[0]['status'] == 'canceled_unavailable'
    assert account.cash == 100


def test_future_events_cannot_change_earlier_decisions():
    replay, ticker, account, now = prepared()
    decision = dict(account.decisions[0])
    replay.state.markets[ticker]['result'] = 'no'
    replay._settle(account, now + 200 * NS)
    assert account.decisions[0] == decision


def test_invalid_experiment_rejected():
    with pytest.raises(ValueError, match='Maker'):
        Experiment(execution='maker')
    with pytest.raises(ValueError):
        Experiment(risk_per_market='101')


def test_unknown_or_increased_series_fees_block_entries():
    replay = Replay()
    replay.state, ticker = warmed_state()
    replay.state.apply(ws(book_frame(ticker, 1, '.40', '.38'), START + 750))
    account = replay.accounts['basic_fair_value']
    replay.state.series['fee_multiplier'] = 2
    replay._decide(account, ticker, int((START + 750.1) * NS))
    assert not account.orders
    assert account.rejected['missing_or_unsupported_series_fees'] == 1
