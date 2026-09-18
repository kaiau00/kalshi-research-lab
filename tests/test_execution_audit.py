import runpy
from decimal import Decimal
from pathlib import Path

from test_engine import prepared
from test_market import START, ws

from research_lab.demo import book_frame
from research_lab.settings import Experiment

audit = runpy.run_path(str(Path(__file__).parents[1] / 'scripts/audit_execution.py'))


def test_independent_audit_catches_tampered_observed_depth():
    original, ticker, account, now = prepared('1.5')
    raw = audit['RawBooks']()
    raw.apply(ws(book_frame(ticker, 1, '.40', '.38', '1.5'), START+750))
    r = audit['CheckedReplay'](original.cfg, raw)
    r.state, r.accounts = original.state, original.accounts
    r._fill_due(account, now+500_000_000)
    assert not r.errors and r.fill_checks[0]['filled'] == 1
    assert all(r.fill_checks[0]['checks'].values())
    original, ticker, account, now = prepared('1.5')
    r = audit['CheckedReplay'](original.cfg, raw)
    r.state, r.accounts = original.state, original.accounts
    raw.books[ticker]['no'][Decimal('.40')] = Decimal(5)
    r._fill_due(account, now+500_000_000)
    assert any('raw_depth_matches' in error for error in r.errors)


def test_independent_rounding_example_and_no_ask_coordinate():
    cfg = Experiment(balance_precision='0.01')
    assert audit['reference_fee'](Decimal('.055'), 1, cfg) == Decimal('.005')
    raw = audit['RawBooks']()
    raw.apply(ws(book_frame('T', 1, '.40', '.38'), START))
    assert raw.best('T', 'no') == (Decimal('.62'), Decimal(10))
