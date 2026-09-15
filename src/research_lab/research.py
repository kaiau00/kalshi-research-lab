from __future__ import annotations

import hashlib
import html
import json
import os
import random
import subprocess
import time
import uuid
from pathlib import Path

from .engine import Replay
from .market import epoch_ns
from .settings import Experiment
from .storage import Store, canonical

LIMITATIONS = [
    'Research only. No live orders and no claim of profitability.',
    'Three separate $100 accounts use the same delayed IOC simulator; returns cannot be added together.',
    'Fill uses the best available level in the book known at the first receipt event after modeled arrival. '
    'This is an execution approximation, not evidence of an actual exchange fill.',
    'Integer contracts only; no maker fills, market impact, queue model, or intramarket exits.',
    'Fee rate and account balance rounding are experiment assumptions and require account/series verification.',
    'Drawdown uses open positions at cost. It understates possible intramarket loss and is not liquidation equity.',
    'Gaussian zero-drift volatility forecasts are hypotheses. Jumps and changing volatility can invalidate them.',
    'Unknown official outcomes remain unresolved; cash tied up in those markets stays unavailable.',
    'Confidence intervals describe observed daily variation, not a guarantee or correction for strategy selection.',
]


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, default=str, allow_nan=False) + '\n')
    temp.replace(path)


def code_revision():
    if os.environ.get('RAILWAY_GIT_COMMIT_SHA'):
        return os.environ['RAILWAY_GIT_COMMIT_SHA']
    try:
        root = Path(__file__).resolve().parents[2]
        sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, stderr=subprocess.DEVNULL,
                                      timeout=3, text=True).strip()
        dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, timeout=3, text=True)
        return sha + ('-dirty' if dirty else '')
    except (OSError, subprocess.SubprocessError):
        return 'unknown'


def source_hash():
    h = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob('*.py')):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def partition(markets):
    # All versions of one market stay together. Boundaries are frozen in the manifest.
    tickers = sorted(markets, key=lambda t: (markets[t], t))
    a, b = int(len(tickers) * .6), int(len(tickers) * .8)
    return {'train': tickers[:a], 'validation': tickers[a:b], 'holdout': tickers[b:]}


def daily_interval(account, observed_days):
    days = sorted(observed_days)
    if len(days) < 20 or account['settled_markets'] < 50:
        return {'available': False, 'reason': 'Requires at least 20 observed UTC days and 50 settled markets.'}
    values = [account['daily_pnl'].get(day, 0.0) for day in days]
    rng = random.Random(1729)
    samples = sorted(sum(rng.choices(values, k=len(values))) / len(values) for _ in range(2000))
    return {'available': True, 'method': 'UTC daily block bootstrap; 2000 draws; seed 1729',
            'observed_days': len(days), 'mean_daily_pnl': sum(values) / len(values),
            'mean_daily_pnl_95pct': [samples[49], samples[1949]]}


def render_report(report):
    m = report['manifest']
    tag = 'SYNTHETIC PIPELINE CHECK — NOT PERFORMANCE EVIDENCE' if report['synthetic'] else 'RECORDED-DATA REPLAY'
    rows = []
    for name, a in report['accounts'].items():
        rows.append('<tr>' + ''.join(f'<td>{html.escape(str(v))}</td>' for v in (
            name, a['settled_markets'], f"${a['realized_net_pnl']:.4f}", f"${a['fees_paid']:.4f}",
            f"${a['cash']:.4f}", a['unresolved_markets'], a['orders_submitted'],
            '—' if a['fill_rate'] is None else f"{a['fill_rate']:.1%}")) + '</tr>')
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Kalshi Research Lab — report</title><style>
body{font:16px system-ui;background:#101720;color:#e5edf4;max-width:1150px;margin:40px auto;padding:24px}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:12px;border-bottom:1px solid #344454}
.label{color:#f4c66a}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#182432;padding:20px}
li{margin:10px 0}a{color:#8fc8ff}</style><h1>Kalshi Research Lab</h1><p class="label">''' + tag + '''</p>
<p>BTC 15-minute markets · independent $100 paper accounts · fees included</p>
<table><thead><tr><th>Strategy</th><th>Settled</th><th>Net P&amp;L</th><th>Fees</th><th>Cash</th>
<th>Unresolved</th><th>Orders</th><th>Fill rate</th></tr></thead><tbody>''' + ''.join(rows) + '''</tbody></table>
<h2>Interpretation limits</h2><ul>''' + ''.join('<li>' + html.escape(s) + '</li>' for s in LIMITATIONS) + '''</ul>
<h2>Frozen experiment</h2><pre>''' + html.escape(json.dumps(m, indent=2, default=str)) + '''</pre>
<h2>Data quality</h2><pre>''' + html.escape(json.dumps(report['quality'], indent=2)) + '''</pre>
<p>The adjacent JSON file contains every decision, order, rejection count, settlement, and uncertainty result.</p></html>'''


def backtest(path, output, cfg=None, split='train', unlock_holdout=False, end_id=None):
    cfg = cfg or Experiment()
    if split not in ('train', 'validation', 'holdout', 'all', 'forward'):
        raise ValueError('Unknown split')
    if split in ('holdout', 'all') and not unlock_holdout:
        raise ValueError('Holdout is sealed. Use --unlock-holdout deliberately; the report logs this disclosure.')
    store = Store(path, readonly=True)
    try:
        prefix = store.prefix()
        end = prefix['last_event_id'] if end_id is None else end_id
        if end < 0 or end > prefix['last_event_id']:
            raise ValueError('Invalid data prefix')
        if end > int(os.environ.get('LAB_MAX_REPLAY_EVENTS', '2000000')):
            raise ValueError('Replay size limit reached; export/archive and use an offline research run.')
        markets, digest, days_by_market, registration = {}, '0' * 64, {}, None
        from datetime import datetime, timezone
        for e in store.events(end):
            digest = hashlib.sha256(bytes.fromhex(digest) + canonical(
                [e.received_ns, e.source_ns, e.kind, e.payload])).hexdigest()
            if digest != e.digest:
                raise ValueError(f'Raw event integrity failure at {e.id}')
            if e.id == 1 and e.kind == 'experiment_registration':
                registration = e.payload
            if e.kind == 'market':
                market = e.payload['market']
                try:
                    close = epoch_ns(market['close_time'])
                    ticker = market['ticker']
                    if ticker.startswith('KXBTC15M-'):
                        markets[ticker] = close
                        days_by_market[ticker] = datetime.fromtimestamp(close / 1e9, timezone.utc).date().isoformat()
                except (KeyError, ValueError, TypeError):
                    pass
        groups = partition(markets)
        if split == 'forward':
            if (not registration or registration.get('config') != cfg.to_dict()
                    or registration.get('source_sha256') != source_hash()):
                raise ValueError('Forward replay requires matching code/config registered before collection began.')
        allowed = list(markets) if split in ('all', 'forward') else groups[split]
        replay = Replay(cfg, set(allowed))
        for e in store.events(end):
            replay.feed(e)
        report = replay.results()
        days = {days_by_market[t] for t in allowed}
        for account in report['accounts'].values():
            account['uncertainty'] = daily_interval(account, days)
        report['manifest'] = {
            'created_ns': time.time_ns(), 'code_revision': code_revision(), 'source_sha256': source_hash(),
            'data': {'last_event_id': end, 'sha256_chain': digest},
            'config': cfg.to_dict(), 'config_sha256': hashlib.sha256(canonical(cfg.to_dict())).hexdigest(),
            'split': split, 'partitions': groups, 'holdout_disclosed': split in ('holdout', 'all'),
            'eligible_markets': len(allowed), 'limitations': LIMITATIONS,
            'prospective_registration': registration if split == 'forward' else None,
            'selection_warning': 'Splits apply to this frozen prefix only. Repartitioning later can expose an old holdout. '
                                 'Freeze a dataset before tuning and compare identical manifests.',
        }
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        run_id = f'{time.time_ns()}-{uuid.uuid4().hex[:8]}'
        write_json(output / (run_id + '.json'), report)
        (output / (run_id + '.html')).write_text(render_report(report))
        return output / (run_id + '.json')
    finally:
        store.close()
