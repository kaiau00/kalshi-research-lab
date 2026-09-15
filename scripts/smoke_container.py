"""Runs inside an isolated CI container; it has no network or Kalshi credentials."""
import base64
import json
import os
import time
import urllib.error
import urllib.request

base = 'http://127.0.0.1:8000'
for _ in range(30):
    try:
        with urllib.request.urlopen(base + '/healthz', timeout=1) as response:
            assert json.load(response)['process_healthy']
        break
    except (urllib.error.URLError, TimeoutError):
        time.sleep(.5)
else:
    raise RuntimeError('Container did not start')
for path, expected in (('/', 401), ('/readyz', 503)):
    try:
        urllib.request.urlopen(base + path, timeout=2)
    except urllib.error.HTTPError as exc:
        assert exc.code == expected
    else:
        raise AssertionError(f'{path} should return {expected}')
token = base64.b64encode(('lab:' + os.environ['LAB_DASHBOARD_PASSWORD']).encode()).decode()
request = urllib.request.Request(base + '/', headers={'Authorization': 'Basic ' + token})
with urllib.request.urlopen(request, timeout=2) as response:
    assert b'Kalshi Research Lab' in response.read()
print('Container healthy; dashboard protected and packaged; missing-feed readiness correctly fails.')
