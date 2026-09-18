"""Retrospective execution diagnostics on frozen archives; never a forward selection run."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import tempfile
from dataclasses import replace
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path

from research_lab.engine import Replay
from research_lab.research import source_hash
from research_lab.segments import Bucket, archive_events, catalog
from research_lab.settings import Experiment


def reference_fee(price, count, cfg):
    revenue = -price * count
    trade_fee = (Decimal(cfg.taker_fee_rate) * count * price * (1-price)).quantize(
        Decimal('.000001'), rounding=ROUND_CEILING)
    change = (revenue-trade_fee).quantize(Decimal(cfg.balance_precision), rounding=ROUND_FLOOR)
    return revenue-change


class RawBooks:
    """Independent reconstruction in the feed's YES price coordinates."""
    def __init__(self):
        self.books, self.seq = {}, {}

    def apply(self, e):
        if e.kind == 'gap' and e.payload.get('stream') != 'benchmark':
            self.books.clear()
            self.seq.clear()
        if e.kind != 'ws':
            return
        f = e.payload['frame']
        if 'sid' in f and 'seq' in f:
            key = (e.payload['session'], f['sid'])
            previous = self.seq.get(key)
            if previous is not None and f['seq'] <= previous:
                return
            if previous is not None and f['seq'] != previous+1:
                self.books.clear()
            self.seq[key] = f['seq']
        if f.get('type') not in ('orderbook_snapshot', 'orderbook_delta'):
            return
        if e.payload.get('book_convention') != 'yes_price':
            raise ValueError('Unknown audit convention')
        m = f['msg']
        ticker = m['market_ticker']
        if f['type'] == 'orderbook_snapshot':
            self.books[ticker] = {s: {Decimal(p): Decimal(q) for p, q in m.get(s+'_dollars_fp', [])}
                                  for s in ('yes', 'no')}
        elif ticker in self.books:
            levels = self.books[ticker][m['side']]
            p = Decimal(m['price_dollars'])
            levels[p] = levels.get(p, Decimal(0)) + Decimal(m['delta_fp'])
            if levels[p] < 0:
                raise ValueError('Negative independent depth')
        if ticker in self.books:
            self.books[ticker]['at_ns'] = e.received_ns

    def best(self, ticker, side):
        b = self.books[ticker]
        levels = b['no' if side == 'yes' else 'yes']
        return min((p if side == 'yes' else 1-p, q) for p, q in levels.items() if q > 0)


class CheckedReplay(Replay):
    def __init__(self, cfg, books, depth=Decimal(1)):
        super().__init__(cfg)
        self.raw_books, self.depth = books, depth
        self.fill_checks, self.errors = [], []

    def _fill_due(self, account, now):
        pending = [(t, o) for t, o in account.pending.items() if now >= o['arrival_ns']]
        saved = {}
        if self.depth != 1:
            for t, _ in pending:
                if t in self.state.books:
                    saved[t] = self.state.books[t]
                    b = copy.copy(saved[t])
                    b.yes = {p: q*self.depth for p, q in b.yes.items()}
                    b.no = {p: q*self.depth for p, q in b.no.items()}
                    self.state.books[t] = b
        try:
            super()._fill_due(account, now)
        finally:
            self.state.books.update(saved)
        for ticker, o in pending:
            if 'fill_ns' not in o:
                continue
            p, q = self.raw_books.best(ticker, o['side'])
            checks = {
                'arrival_respected': o['fill_ns'] >= o['arrival_ns'],
                'limit_respected': o['fill_price'] <= o['limit'],
                'raw_book_price_matches': o['fill_price'] == p,
                'raw_depth_matches': o['filled'] == min(o['quantity'], int(q*self.depth)),
                'raw_book_fresh': 0 <= now-self.raw_books.books[ticker]['at_ns'] <= self.cfg.max_book_age_ms*1000000,
                'fee_matches_independent_rounding': o['fees'] == reference_fee(p, o['filled'], self.cfg),
                'cost_reconciles': o['cost'] == p*o['filled']+o['fees'],
                'reservation_respected': o['cost'] <= o['reservation'],
                'risk_respected': o['cost'] <= Decimal(self.cfg.risk_per_market),
                'cash_nonnegative': account.cash >= account.reserved >= 0,
            }
            row = {'strategy': account.name, 'ticker': ticker, 'side': o['side'],
                   'created_ns': o['created_ns'], 'fill_ns': now,
                   'arrival_overshoot_ms': (now-o['arrival_ns'])/1000000,
                   'limit': str(o['limit']), 'fill_price': str(p), 'raw_depth': str(q),
                   'filled': o['filled'], 'fees': str(o['fees']), 'cost': str(o['cost']), 'checks': checks}
            self.fill_checks.append(row)
            self.errors.extend(f'{account.name}:{ticker}:{k}' for k, v in checks.items() if not v)


def scenarios(books):
    cfg = Experiment()
    return {
        'baseline_500ms': CheckedReplay(cfg, books),
        'latency_1500ms': CheckedReplay(replace(cfg, latency_ms=1500), books),
        'latency_3000ms': CheckedReplay(replace(cfg, latency_ms=3000), books),
        'half_displayed_depth': CheckedReplay(cfg, books, Decimal('.5')),
        'cent_balance_rounding': CheckedReplay(replace(cfg, balance_precision='0.01'), books),
        'combined_adverse': CheckedReplay(replace(cfg, latency_ms=3000, balance_precision='0.01',
                                         taker_fee_rate='0.14', max_book_age_ms=500), books, Decimal('.25')),
    }


def summary(replay):
    accounts = {}
    for name, a in replay.accounts.items():
        costs = sum((o['cost'] for o in a.orders if 'cost' in o), Decimal(0))
        payouts = sum((o['payout'] for o in a.closed), Decimal(0))
        checks = {'cash_reconciles': a.cash == Decimal(replay.cfg.bankroll)-costs+payouts,
                  'reservations_reconcile': a.reserved == sum((o['reservation'] for o in a.pending.values()), Decimal(0)),
                  'one_fill_per_market': len({o['ticker'] for o in a.orders if 'fill_ns' in o}) == sum('fill_ns' in o for o in a.orders)}
        replay.errors.extend(f'{name}:{k}' for k, v in checks.items() if not v)
        accounts[name] = {'cash': str(a.cash), 'realized_net_pnl': str(sum((o['pnl'] for o in a.closed), Decimal(0))),
                          'fees': str(sum((o.get('fees', Decimal(0)) for o in a.orders), Decimal(0))),
                          'orders': len(a.orders), 'fills': sum('fill_ns' in o for o in a.orders),
                          'settled': len(a.closed), 'open': len(a.positions), 'pending': len(a.pending),
                          'accounting_checks': checks}
    return {'config': replay.cfg.to_dict(), 'depth_fraction': str(replay.depth), 'accounts': accounts,
            'fill_checks': replay.fill_checks, 'failures': replay.errors}


def run(root, max_segments, output):
    if max_segments < 1 or max_segments > 50:
        raise ValueError('Audit limited to 1–50 archived segments')
    cat = catalog(root)
    rows = [dict(r) for r in cat.execute("SELECT * FROM segments WHERE status='archived' ORDER BY id LIMIT ?", (max_segments,))]
    dataset = cat.execute("SELECT value FROM settings WHERE key='dataset'").fetchone()[0]
    cat.close()
    if len(rows) != max_segments or [r['id'] for r in rows] != list(range(max_segments)):
        raise ValueError('A contiguous archived prefix from registration is required')
    books = RawBooks()
    replays = scenarios(books)
    previous = '0'*64
    registration = None
    bucket = Bucket()
    with tempfile.TemporaryDirectory() as td:
        for row in rows:
            if row['previous_digest'] != previous:
                raise ValueError('Archive linkage mismatch')
            p = Path(td)/'segment.gz'
            bucket.get(row['archive_key'], p, row['archive_sha'])
            for e in archive_events(p, row):
                if registration is None:
                    if e.kind != 'experiment_registration':
                        raise ValueError('Missing registration')
                    registration = e.payload
                books.apply(e)
                for replay in replays.values():
                    replay.feed(e)
            previous = row['digest']
            print(json.dumps({'segment_complete': row['id']}), flush=True)
    out = {'scope': 'Retrospective execution sensitivity; inspected commissioning data, not holdout or proof of profitability',
           'dataset': dataset, 'archive_segments': max_segments, 'terminal_hash': previous,
           'events': replays['baseline_500ms'].event_count, 'receipt_cutoff_ns': replays['baseline_500ms'].last_ns,
           'recorded_registration': registration, 'audit_source_sha256': source_hash(),
           'audit_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           'fee_limitations': 'Historical event overrides were not captured; direct versus broker precision is tested, not account-certified. Single aggregate best-level fills do not validate real exchange matching.',
           'scenarios': {n: summary(r) for n, r in replays.items()}}
    Path(output).write_text(json.dumps(out, indent=2, default=str)+'\n')
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--max-segments', type=int, default=24)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.root, args.max_segments, args.output)
