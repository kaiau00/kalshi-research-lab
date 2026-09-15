import json

import pytest
from fastapi.testclient import TestClient

from research_lab.app import create_app
from research_lab.demo import create_demo
from research_lab.research import backtest, partition, source_hash
from research_lab.settings import Experiment
from research_lab.storage import Store


def test_synthetic_end_to_end_and_repeatability(tmp_path):
    path = tmp_path / 'synthetic.db'
    create_demo(path, markets=5)
    with pytest.raises(ValueError, match='sealed'):
        backtest(path, tmp_path, split='all')
    first = json.loads(backtest(path, tmp_path, split='all', unlock_holdout=True).read_text())
    second = json.loads(backtest(path, tmp_path, split='all', unlock_holdout=True).read_text())
    assert first['accounts'] == second['accounts']
    assert first['synthetic']
    assert first['quality']['clock_adjustments'] == 0
    assert first['manifest']['data'] == second['manifest']['data']
    for account in first['accounts'].values():
        assert account['settled_markets'] == 5
        assert account['cash'] == pytest.approx(100 + account['realized_net_pnl'])
        assert account['unresolved_markets'] == 0
        assert not account['uncertainty']['available']


def test_market_partitions_are_disjoint_and_chronological():
    groups = partition({f'm{i}': i for i in range(10)})
    assert list(map(len, groups.values())) == [6, 2, 2]
    assert set(groups['train']).isdisjoint(groups['holdout'])
    assert groups['validation'] == ['m6', 'm7']


def test_forward_requires_preregistered_code_and_settings(tmp_path):
    path = tmp_path / 'raw.db'
    store = Store(path)
    store.append('experiment_registration', {'config': Experiment().to_dict(), 'source_sha256': source_hash()})
    store.close()
    backtest(path, tmp_path, split='forward')
    with pytest.raises(ValueError, match='matching'):
        backtest(path, tmp_path, cfg=Experiment(min_edge=.10), split='forward')


def test_dashboard_auth_health_and_job_guards(monkeypatch):
    monkeypatch.setenv('LAB_DASHBOARD_PASSWORD', 'a-private-test-password')
    with TestClient(create_app(record=False)) as client:
        assert client.get('/healthz').status_code == 200
        assert client.get('/readyz').status_code == 503
        assert client.get('/').status_code == 401
        auth = ('lab', 'a-private-test-password')
        assert client.get('/', auth=auth).status_code == 200
        assert client.get('/api/status', auth=auth).json()['recorder']['mode'] == 'disabled'
        assert client.post('/api/replay', auth=auth, json={}).status_code == 403
        assert client.post('/api/replay', auth=auth, json={'split': 'holdout'},
                           headers={'X-Research-Lab': '1'}).status_code == 400
        assert client.get('/reports/not-a-report', auth=auth).status_code == 404
