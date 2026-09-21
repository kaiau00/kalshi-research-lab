import hashlib
import json
import runpy
from pathlib import Path

import pytest

from research_lab.checkpoint import encode
from research_lab.demo import create_demo
from research_lab.engine import Replay
from research_lab.storage import Store, canonical

analysis = runpy.run_path(str(Path(__file__).parents[1] / 'scripts/compare_registered.py'))


def fixture(tmp_path):
    path = tmp_path/'demo.db'
    create_demo(path, markets=10)
    source = Store(path, readonly=True)
    replay = Replay()
    for e in source.events():
        replay.feed(e)
    source.close()
    data = {'source': 'registered-source', 'dataset': 'fixture', 'next_segment': 10,
            'last_digest': 'a'*64, 'replay': encode(replay)}
    manifest = analysis['make_manifest'](data, replay, 1800000000*10**9, 'checkpoint-sha', 'catalog-sha')
    return replay, data, manifest


def test_market_splits_do_not_disclose_holdout_performance(tmp_path):
    replay, _, manifest = fixture(tmp_path)
    assert [len(manifest['partitions'][k]) for k in ('train', 'validation', 'holdout')] == [6, 2, 2]
    before = analysis['group_summary'](replay, manifest, 'train')
    holdout = set(manifest['partitions']['holdout'])
    for account in replay.accounts.values():
        for trade in account.closed:
            if trade['ticker'] in holdout:
                trade['pnl'] += 999
                trade['probability'] = -999
    assert analysis['group_summary'](replay, manifest, 'train') == before
    with pytest.raises(ValueError, match='sealed'):
        analysis['group_summary'](replay, manifest, 'holdout')
    assert not any(a['uncertainty']['available'] for a in before['accounts'].values())


def test_checkpoint_integrity_and_cash_reconciliation_fail_closed(tmp_path):
    _, data, _ = fixture(tmp_path)
    raw = json.dumps({'data': data, 'sha256': hashlib.sha256(canonical(data)).hexdigest()})
    _, replay = analysis['verify_checkpoint'](raw)
    replay.accounts['basic_fair_value'].cash += 1
    data['replay'] = encode(replay)
    with pytest.raises(ValueError, match='checksum'):
        analysis['verify_checkpoint'](json.dumps({'data': data, 'sha256': 'bad'}))
    with pytest.raises(ValueError, match='Cash'):
        analysis['verify_checkpoint'](json.dumps({'data': data, 'sha256': hashlib.sha256(canonical(data)).hexdigest()}))


def test_delayed_training_settlement_blocks_validation_claim(tmp_path):
    replay, _, manifest = fixture(tmp_path)
    account = replay.accounts['basic_fair_value']
    training = [o for o in account.closed if o['ticker'] in manifest['partitions']['train']]
    validation = [o for o in account.orders if o['ticker'] in manifest['partitions']['validation']]
    assert training and validation
    training[-1]['settled_ns'] = min(o['created_ns'] for o in validation)+1
    result = analysis['group_summary'](replay, manifest, 'validation')
    assert not result['accounts']['basic_fair_value']['training_settlements_precede_validation_decisions']
