"""Check the largest already-disclosed validation win against original archived frames."""
import json
import runpy
import tempfile
from decimal import Decimal
from pathlib import Path

from research_lab.market import epoch_ns
from research_lab.segments import Bucket, archive_events, catalog


def audit(root, bundle):
    analysis = runpy.run_path(str(Path(__file__).with_name('compare_registered.py')))
    books = runpy.run_path(str(Path(__file__).with_name('audit_execution.py')))['RawBooks']()
    manifest = json.loads((Path(bundle)/'manifest.json').read_text())
    raw = (Path(bundle)/'checkpoint.json').read_bytes()
    import hashlib
    if hashlib.sha256(raw).hexdigest() != manifest['checkpoint_sha256']:
        raise ValueError('Frozen checkpoint changed')
    _, replay = analysis['verify_checkpoint'](raw)
    trades = [o for o in replay.accounts['basic_fair_value'].closed if o['ticker'] in manifest['partitions']['validation']]
    winner = max(trades, key=lambda o: o['pnl'])
    market = replay.state.markets[winner['ticker']]
    start = epoch_ns(market['open_time'])-1000_000_000_000
    end = winner['settled_ns']+1_000_000_000
    c = catalog(root)
    rows = []
    for row in c.execute("SELECT * FROM segments WHERE status='archived' AND id < ? ORDER BY id", (manifest['next_segment'],)):
        streams = json.loads(row['stats'])['streams']
        if max(s['last_ns'] for s in streams) >= start and min(s['first_ns'] for s in streams) <= end:
            rows.append(dict(row))
    c.close()
    if not 1 <= len(rows) <= 30:
        raise ValueError('Selected fill exceeds the bounded audit window')
    found, finalized = {}, None
    bucket = Bucket()
    with tempfile.TemporaryDirectory() as td:
        path = Path(td)/'segment.gz'
        for row in rows:
            bucket.get(row['archive_key'], path, row['archive_sha'])
            for e in archive_events(path, row):
                books.apply(e)
                for label, timestamp in [('decision', winner['created_ns']), ('fill', winner['fill_ns'])]:
                    if e.received_ns == timestamp:
                        price, quantity = books.best(winner['ticker'], winner['side'])
                        found[label] = {'receipt_ns': timestamp, 'price': str(price), 'depth': str(quantity),
                                        'book_receipt_ns': books.books[winner['ticker']]['at_ns'],
                                        'segment': row['id'], 'event': e.id}
                if (e.kind == 'market' and e.payload['market']['ticker'] == winner['ticker']
                        and e.payload['market'].get('status') == 'finalized' and e.received_ns == winner['settled_ns']):
                    finalized = {'receipt_ns': e.received_ns, 'result': e.payload['market']['result']}
    checks = {'decision_quote_matches_limit': Decimal(found['decision']['price']) == winner['limit'],
              'fill_price_matches': Decimal(found['fill']['price']) == winner['fill_price'],
              'quantity_within_depth': winner['filled'] <= int(Decimal(found['fill']['depth'])),
              'book_within_freshness_limit': winner['fill_ns']-found['fill']['book_receipt_ns'] <= replay.cfg.max_book_age_ms*1000000,
              'arrival_latency_respected': winner['fill_ns'] >= winner['arrival_ns'],
              'official_finalization_matches': bool(finalized and finalized['result'] == winner['result']),
              'pnl_reconciles': winner['payout']-winner['cost'] == winner['pnl']}
    return {'scope': 'One already-disclosed validation winner; no holdout data reported; no actual exchange fill claim',
            'dataset': manifest['dataset'], 'checkpoint_sha256': manifest['checkpoint_sha256'],
            'market': winner['ticker'], 'pnl': str(winner['pnl']), 'filled': winner['filled'],
            'side': winner['side'], 'verified_archive_segments': [r['id'] for r in rows],
            'observations': found, 'finalization': finalized, 'checks': checks}


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True)
    p.add_argument('--bundle', required=True)
    args = p.parse_args()
    print(json.dumps(audit(args.root, args.bundle), indent=2))
