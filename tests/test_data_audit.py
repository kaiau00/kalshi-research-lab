import runpy
from pathlib import Path

import pytest

from research_lab.demo import book_frame, index_frame, market_fixture
from research_lab.storage import Store

audit = runpy.run_path(str(Path(__file__).parents[1] / 'scripts/audit_data.py'))['audit']
NS = 10**9
START = 1800000000


@pytest.mark.parametrize('omit_first', [False, True])
def test_audit_final_minute_boundaries_missing_ticks_and_book_coverage(tmp_path, omit_first):
    path = tmp_path / 'events.db'
    store = Store(path)
    m = market_fixture()
    store.append('market', {'market': m}, received_ns=START * NS)

    def ws(frame, second):
        store.append('ws', {'frame': frame, 'session': 's', 'book_convention': 'yes_price'},
                     received_ns=second * NS, source_ns=second * NS)

    ws(book_frame(m['ticker'], 1), START + 1)
    empty = {'type': 'orderbook_snapshot', 'sid': 1, 'seq': 2, 'msg': {'market_ticker': m['ticker']}}
    ws(empty, START + 4)
    # Include the start boundary in settlement; exclude the close boundary.
    for offset in range(840 + int(omit_first), 900):
        ws(index_frame(START + offset, 80001), START + offset)
    ws(index_frame(START + 900, 1), START + 900)
    store.append('market', {'market': {**m, 'status': 'finalized', 'result': 'yes',
                                      'expiration_value': '80001.00'}}, received_ns=(START + 901) * NS)
    store.close()
    report = audit(path)
    row = report['markets'][0]
    assert report['hash_matches_frozen_prefix']
    assert report['normalizer_quality']['malformed'] == 0
    assert row['book_coverage_seconds']['two_sided'] == 3
    assert row['book_coverage_seconds']['fresh_two_sided'] == 2
    assert row['final_minute_count'] == 60 - int(omit_first)
    assert row['recorded_settlement_matches'] is (None if omit_first else True)
    assert row['recorded_result_matches'] is (None if omit_first else True)
    assert row['reconstructed_settlement'] == (None if omit_first else '80001.00')
    assert row['benchmark_seconds_present'] < row['benchmark_seconds_expected']
