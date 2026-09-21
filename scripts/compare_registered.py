"""Freeze and attribute a registered forward ledger without disclosing holdout P&L."""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from research_lab.checkpoint import decode
from research_lab.market import epoch_ns
from research_lab.research import daily_interval, partition, write_json
from research_lab.segments import Bucket, archive_events, catalog
from research_lab.storage import canonical


def verify_checkpoint(raw):
    envelope = json.loads(raw)
    data = envelope['data']
    if hashlib.sha256(canonical(data)).hexdigest() != envelope['sha256']:
        raise ValueError('Checkpoint checksum mismatch')
    replay = decode(data['replay'])
    for a in replay.accounts.values():
        costs = sum((o.get('cost', Decimal(0)) for o in a.orders), Decimal(0))
        payouts = sum((o['payout'] for o in a.closed), Decimal(0))
        if a.cash != Decimal(replay.cfg.bankroll)-costs+payouts:
            raise ValueError('Cash ledger mismatch')
        if a.reserved != sum((o['reservation'] for o in a.pending.values()), Decimal(0)):
            raise ValueError('Reservation mismatch')
        if any(not any(o is item for item in a.orders) for o in [*a.pending.values(), *a.positions.values()]):
            raise ValueError('Account order identity mismatch')
    return data, replay


def make_manifest(data, replay, registration_ns, checkpoint_sha, catalog_sha):
    markets = {t: epoch_ns(m['close_time']) for t, m in replay.state.markets.items()
               if t.startswith('KXBTC15M-') and epoch_ns(m['close_time']) <= replay.last_ns}
    groups = partition(markets)
    partial = [t for t in markets if epoch_ns(replay.state.markets[t]['open_time']) < registration_ns]
    return {'version': 1, 'created_ns': time.time_ns(), 'dataset': data['dataset'],
            'checkpoint_sha256': checkpoint_sha, 'catalog_prefix_sha256': catalog_sha,
            'registered_source_sha256': data['source'], 'config': replay.cfg.to_dict(),
            'next_segment': data['next_segment'], 'terminal_hash': data['last_digest'],
            'events': replay.event_count, 'registration_ns': registration_ns,
            'receipt_cutoff_ns': replay.last_ns, 'market_closes_ns': markets,
            'partitions': groups, 'startup_partial_markets': partial,
            'not_closed_at_cutoff': sorted(set(replay.state.markets)-set(markets)),
            'scope': 'Attribution of original continuous forward accounts; no bankroll resets or parameter changes',
            'prior_disclosure': 'v5 fill counts and accounting were checked; v5 strategy P&L was not inspected',
            'holdout_performance_disclosed': False}


def freeze(root, destination, bucket=None):
    root, destination = Path(root), Path(destination)
    if destination.exists():
        raise ValueError('Refusing to overwrite a frozen comparison')
    raw = (root/'checkpoint.json').read_bytes()
    data, replay = verify_checkpoint(raw)
    c = catalog(root)
    try:
        dataset = c.execute("SELECT value FROM settings WHERE key='dataset'").fetchone()[0]
        rows = [dict(r) for r in c.execute('SELECT * FROM segments WHERE id < ? ORDER BY id', (data['next_segment'],))]
    finally:
        c.close()
    if (dataset != data['dataset'] or len(rows) != data['next_segment'] or not rows
            or [r['id'] for r in rows] != list(range(len(rows)))
            or any(r['status'] != 'archived' for r in rows)
            or sum(r['count'] for r in rows) != replay.event_count
            or rows[-1]['digest'] != data['last_digest']):
        raise ValueError('Catalog/checkpoint prefix mismatch')
    previous = '0'*64
    for row in rows:
        if row['previous_digest'] != previous:
            raise ValueError('Catalog chain mismatch')
        previous = row['digest']
    with tempfile.TemporaryDirectory() as td:
        path = Path(td)/'registration.gz'
        bucket = bucket or Bucket()
        bucket.get(rows[0]['archive_key'], path, rows[0]['archive_sha'])
        first = None
        for e in archive_events(path, rows[0]):
            if first is None:
                first = e
        if (first.kind != 'experiment_registration' or first.payload['source_sha256'] != data['source']
                or first.payload['config'] != replay.cfg.to_dict()):
            raise ValueError('Forward registration mismatch')
    source_manifest = [{k: r[k] for k in ('id', 'count', 'digest', 'previous_digest', 'archive_key', 'archive_sha')}
                       for r in rows]
    manifest = make_manifest(data, replay, first.received_ns, hashlib.sha256(raw).hexdigest(),
                             hashlib.sha256(canonical(source_manifest)).hexdigest())
    destination.mkdir(parents=True)
    (destination/'checkpoint.json').write_bytes(raw)
    write_json(destination/'archive-prefix.json', source_manifest)
    write_json(destination/'manifest.json', manifest)
    write_json(destination/'disclosures.json', [])
    return manifest


def group_summary(replay, manifest, split):
    if split not in ('train', 'validation'):
        raise ValueError('Holdout remains sealed; only train and validation reports are supported')
    selected = set(manifest['partitions'][split])
    observed_days = {datetime.fromtimestamp(manifest['market_closes_ns'][t]/1e9, timezone.utc).date().isoformat()
                     for t in selected}
    results = {}
    for name, a in replay.accounts.items():
        orders = [o for o in a.orders if o['ticker'] in selected]
        closed = sorted((o for o in a.closed if o['ticker'] in selected), key=lambda o: o['settled_ns'])
        positions = [o for t, o in a.positions.items() if t in selected]
        pending = [o for t, o in a.pending.items() if t in selected]
        pnl = sum((o['pnl'] for o in closed), Decimal(0))
        fees = sum((o.get('fees', Decimal(0)) for o in orders), Decimal(0))
        daily = {d: {'net_pnl': Decimal(0), 'settled_markets': 0} for d in observed_days}
        equity, peak, dd = Decimal(0), Decimal(0), Decimal(0)
        for o in closed:
            day = datetime.fromtimestamp(o['settled_ns']/1e9, timezone.utc).date().isoformat()
            daily.setdefault(day, {'net_pnl': Decimal(0), 'settled_markets': 0})
            daily[day]['net_pnl'] += o['pnl']
            daily[day]['settled_markets'] += 1
            equity += o['pnl']
            peak = max(peak, equity)
            dd = max(dd, peak-equity)
        filled = sum('fill_ns' in o for o in orders)
        status_counts = {}
        for o in orders:
            status_counts[o['status']] = status_counts.get(o['status'], 0)+1
        training_closed = [o for o in a.closed if o['ticker'] in manifest['partitions']['train']]
        training_unresolved = any(t in manifest['partitions']['train'] for t in a.positions)
        first_decision = min((o['created_ns'] for o in orders), default=None)
        timing_clear = (not training_unresolved and (split == 'train' or first_decision is None
                        or max((o['settled_ns'] for o in training_closed), default=0) < first_decision))
        uncertainty = daily_interval({'settled_markets': len(closed),
                                      'daily_pnl': {d: float(v['net_pnl']) for d, v in daily.items()}}, set(daily))
        results[name] = {'net_pnl': str(pnl), 'gross_pnl': str(pnl+sum((o['fees'] for o in closed), Decimal(0))),
                        'fees_paid': str(fees), 'orders': len(orders), 'filled_markets': filled,
                        'settled_markets': len(closed), 'win_rate': sum(o['won'] for o in closed)/len(closed) if closed else None,
                        'fill_rate': filled/len(orders) if orders else None, 'max_drawdown_cost_basis': str(dd),
                        'open_cost': str(sum((o['cost'] for o in positions), Decimal(0))),
                        'unresolved_positions': len(positions), 'pending_orders': len(pending),
                        'status_counts': status_counts, 'daily': daily, 'observed_utc_days': len(daily),
                        'mean_predicted_win_probability': sum(o['probability'] for o in closed)/len(closed) if closed else None,
                        'brier_score': sum((o['probability']-o['won'])**2 for o in closed)/len(closed) if closed else None,
                        'startup_partial_pnl': str(sum((o['pnl'] for o in closed if o['ticker'] in manifest['startup_partial_markets']), Decimal(0))),
                        'training_settlements_precede_validation_decisions': timing_clear,
                        'uncertainty': uncertainty}
    return {'split': split, 'eligible_markets': len(selected), 'source': {k: manifest[k] for k in
            ('dataset', 'checkpoint_sha256', 'registered_source_sha256', 'terminal_hash', 'receipt_cutoff_ns')},
            'scope': manifest['scope'], 'config': manifest['config'], 'accounts': results,
            'unresolved_market_outcomes': sorted(t for t in selected if replay.state.markets[t].get('status') != 'finalized'),
            'holdout_performance_disclosed': False,
            'limitations': ['This is a short sample, not proof of an edge.',
                           'Validation attributes the continuing original account; no fresh bankroll replay.',
                           'Drawdown values open positions at cost, not liquidation value.',
                           'Order-level rejection statuses are shown; per-decision rejection counts cannot be split from aggregated counters.',
                           'No new full-dataset execution stress or parameter search is claimed.',
                           'Direct-member fee precision assumed; actual account channel remains unconfirmed.',
                           'Hosting costs are not deducted from strategy P&L.']}


def report(bundle, split):
    bundle = Path(bundle)
    manifest = json.loads((bundle/'manifest.json').read_text())
    raw = (bundle/'checkpoint.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest['checkpoint_sha256']:
        raise ValueError('Frozen checkpoint changed')
    data, replay = verify_checkpoint(raw)
    if data['dataset'] != manifest['dataset'] or data['source'] != manifest['registered_source_sha256']:
        raise ValueError('Frozen source mismatch')
    out = group_summary(replay, manifest, split)
    out['analysis_script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    disclosures = json.loads((bundle/'disclosures.json').read_text())
    disclosures.append({'split': split, 'opened_ns': time.time_ns(), 'purpose': 'Fixed-setting descriptive comparison'})
    write_json(bundle/'disclosures.json', disclosures)
    write_json(bundle/(split+'.json'), out)
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    f = sub.add_parser('freeze')
    f.add_argument('--root', type=Path, required=True)
    f.add_argument('--output', type=Path, required=True)
    r = sub.add_parser('report')
    r.add_argument('--bundle', type=Path, required=True)
    r.add_argument('--split', choices=['train', 'validation'], required=True)
    args = parser.parse_args()
    result = freeze(args.root, args.output) if args.command == 'freeze' else report(args.bundle, args.split)
    print(json.dumps(result, indent=2, default=str))
