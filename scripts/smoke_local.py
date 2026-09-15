"""Bounded public-data commissioning check; never reads a Kalshi key or places orders."""
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from research_lab.storage import Store

root = Path(__file__).resolve().parents[1]
data = root / 'data' / ('smoke-' + str(time.time_ns()))
data.mkdir(parents=True)
secret = secrets.token_urlsafe(24)
env = {k: v for k, v in os.environ.items() if not k.startswith('KALSHI_')}
env.update(LAB_DATA_DIR=str(data), LAB_DASHBOARD_PASSWORD=secret, PYTHONPATH=str(root / 'src'))
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
base = f'http://127.0.0.1:{port}'
checks = []
for attempt in range(2):
    with (data / f'process-{attempt}.log').open('w') as log:
        proc = subprocess.Popen([sys.executable, '-m', 'research_lab.cli', 'serve', '--port', str(port)],
                                cwd=root, env=env, stdout=log, stderr=log)
        try:
            with httpx.Client(base_url=base, timeout=2) as client:
                status = None
                for _ in range(30):
                    try:
                        response = client.get('/api/status', auth=('lab', secret))
                        if response.status_code == 200:
                            status = response.json()
                            if status['recorder']['last_discovery_ns']:
                                break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.5)
                assert status and status['recorder']['last_discovery_ns'], 'Public discovery failed'
                assert client.get('/healthz').status_code == 200
                assert client.get('/readyz').status_code == 503
                assert client.get('/').status_code == 401
                assert client.get('/', auth=('lab', secret)).status_code == 200
                assert status['recorder']['mode'] == 'waiting_for_credentials'
                checks.append({'restart': attempt, 'public_discovery': True, 'auth_required': True,
                               'health': 200, 'data_readiness_without_key': 503,
                               'event_prefix': status['storage']['prefix']})
        finally:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
store = Store(data / 'events.sqlite3', readonly=True)
try:
    integrity = store.verify()
    registrations = sum(e.kind == 'experiment_registration' for e in store.events())
    assert registrations == 1
finally:
    store.close()
result = {'checks': checks, 'integrity': integrity, 'experiment_registrations_after_restart': registrations,
          'authenticated_feed_tested': False, 'live_orders_possible': False}
out = root / 'docs' / 'validation' / 'local-smoke.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
