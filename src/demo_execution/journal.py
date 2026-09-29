from __future__ import annotations

import json
import sqlite3
import time
from decimal import Decimal
from pathlib import Path


def dumps(value):
    return json.dumps(value, default=str, sort_keys=True, separators=(',', ':'))


class Journal:
    def __init__(self, path, max_order_cost='1.00'):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.max_order_cost = Decimal(max_order_cost)
        if not self.max_order_cost.is_finite() or self.max_order_cost <= 0:
            raise ValueError('Invalid journal order cost limit')
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS intents (
                client_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, created_ns INTEGER NOT NULL,
                payload TEXT NOT NULL, decision TEXT NOT NULL, state TEXT NOT NULL,
                exchange_order TEXT, error TEXT
            );
            CREATE TABLE IF NOT EXISTS settlements (ticker TEXT PRIMARY KEY, response TEXT NOT NULL, pnl TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS shadow_signals (
                variant TEXT NOT NULL, ticker TEXT NOT NULL, created_ns INTEGER NOT NULL,
                decision TEXT NOT NULL, PRIMARY KEY (variant, ticker)
            );
        ''')

    def register(self, config, identity, strategy='basic_fair_value', revision=None):
        strategy_value = dumps({'strategy': strategy})
        old_strategy = self.db.execute(
            "SELECT value FROM metadata WHERE key='strategy_registration'").fetchone()
        if old_strategy and old_strategy[0] != strategy_value:
            raise RuntimeError('Demo strategy changed; preserve ledger and use a new ledger')
        value = dumps({'config': config, 'identity': identity, 'environment': 'demo', 'exchange_index': 2})
        old = self.db.execute("SELECT value FROM metadata WHERE key='registration'").fetchone()
        if old and old[0] != value:
            if not revision:
                raise RuntimeError('Demo registration changed; preserve ledger and review before restarting')
            before, after = json.loads(old[0]), json.loads(value)
            before_cfg, after_cfg = dict(before['config']), dict(after['config'])
            before_risk = before_cfg.pop('risk_per_market', None)
            after_risk = after_cfg.pop('risk_per_market', None)
            settled = {row['ticker'] for row in self.settled()}
            unsettled_fills = [row['ticker'] for row in self.rows()
                               if row['exchange_order']
                               and Decimal(json.loads(row['exchange_order'])['fill_count_fp']) > 0
                               and row['ticker'] not in settled]
            revision_key = 'revision:' + revision
            if (before.get('identity') != after.get('identity') or before_cfg != after_cfg
                    or before_risk != '1.00' or after_risk != '3.00'
                    or self.pending() or unsettled_fills
                    or self.db.execute('SELECT 1 FROM metadata WHERE key=?',
                                       (revision_key,)).fetchone()):
                raise RuntimeError('Demo registration revision is not safe')
            self.db.execute('INSERT INTO metadata VALUES (?,?)',
                            (revision_key, dumps({'from': before, 'to': after,
                                                  'changed_ns': time.time_ns()})))
            self.db.execute("UPDATE metadata SET value=? WHERE key='registration'", (value,))
        self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('registration',?)", (value,))
        self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('strategy_registration',?)",
                        (strategy_value,))
        self.db.commit()

    def register_shadow_variants(self, variants):
        for name, config in variants.items():
            key = 'shadow_variant:' + name
            value = dumps({'strategy': 'tail_underdog', 'config': config,
                           'execution': 'signal_only_no_order'})
            old = self.db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            if old and old[0] != value:
                raise RuntimeError('Shadow variant changed; use a new variant name')
            self.db.execute('INSERT OR IGNORE INTO metadata VALUES (?,?)', (key, value))
        self.db.commit()

    def shadow_signal(self, variant, ticker, decision, created_ns=None):
        result = self.db.execute('INSERT OR IGNORE INTO shadow_signals VALUES (?,?,?,?)',
                                 (variant, ticker, created_ns or time.time_ns(), dumps(decision)))
        self.db.commit()
        return result.rowcount == 1

    def shadow_rows(self, variant=None):
        query = ('SELECT * FROM shadow_signals' + (' WHERE variant=?' if variant else '')
                 + ' ORDER BY created_ns')
        return [dict(r) for r in self.db.execute(query, (variant,) if variant else ())]

    def has_shadow_signal(self, variant, ticker):
        return bool(self.db.execute(
            'SELECT 1 FROM shadow_signals WHERE variant=? AND ticker=?',
            (variant, ticker)).fetchone())

    def shadow_summary(self, variants):
        return {'execution': 'signal_only_no_order',
                'counts': {name: len(self.shadow_rows(name)) for name in variants},
                'recent': [{**r, 'decision': json.loads(r['decision'])}
                           for r in self.shadow_rows()[-10:]]}

    def rows(self, ticker=None):
        return [dict(r) for r in self.db.execute(
            'SELECT * FROM intents' + (' WHERE ticker=?' if ticker else '') + ' ORDER BY created_ns',
            (ticker,) if ticker else ())]

    def pending(self):
        return [r for r in self.rows() if r['state'] not in ('terminal', 'rejected')]

    def intent(self, payload, decision):
        # Commit BEFORE the network write; an uncertain request permanently blocks
        # new submissions until this exact client ID is reconciled, including on restart.
        if self.pending():
            raise RuntimeError('Unreconciled demo order')
        rows = self.rows(payload['ticker'])
        if len(rows) >= 3 or any(r['exchange_order'] and
                               Decimal(json.loads(r['exchange_order'])['fill_count_fp']) > 0 for r in rows):
            raise RuntimeError('Market attempt/fill limit reached')
        self.db.execute('INSERT INTO intents VALUES (?,?,?,?,?,?,?,?)',
                        (payload['client_order_id'], payload['ticker'], time.time_ns(), dumps(payload),
                         dumps(decision), 'intent', None, None))
        self.db.commit()

    def error(self, client_id, reason, *, definitive=False):
        self.db.execute('UPDATE intents SET state=?,error=? WHERE client_id=?',
                        ('rejected' if definitive else 'uncertain', reason, client_id))
        self.db.commit()

    def reconcile(self, client_id, order):
        row = self.db.execute('SELECT * FROM intents WHERE client_id=?', (client_id,)).fetchone()
        payload = json.loads(row['payload'])
        fill = Decimal(order['fill_count_fp'])
        remaining = Decimal(order['remaining_count_fp'])
        expected_outcome = 'yes' if payload['side'] == 'bid' else 'no'
        if (order['client_order_id'] != client_id or order['ticker'] != payload['ticker']
                or order['exchange_index'] != 2 or order.get('subaccount_number', 0) not in (0, None)
                or order['outcome_side'] != expected_outcome or not fill.is_finite()
                or not remaining.is_finite() or not 0 <= fill <= Decimal(payload['count'])
                or remaining != 0 or order['status'] not in ('canceled', 'executed')):
            raise RuntimeError('Unexpected demo order response; stop and reconcile')
        amounts = [Decimal(order[k]) for k in ('taker_fill_cost_dollars', 'maker_fill_cost_dollars',
                                               'taker_fees_dollars', 'maker_fees_dollars')]
        if any(not x.is_finite() or x < 0 for x in amounts) or sum(amounts) > self.max_order_cost:
            raise RuntimeError('Demo order cost exceeded configured budget')
        self.db.execute('UPDATE intents SET state=?,exchange_order=?,error=NULL WHERE client_id=?',
                        ('terminal', dumps(order), client_id))
        self.db.commit()

    def settled(self):
        return [dict(r) for r in self.db.execute('SELECT * FROM settlements')]

    def settlement(self, ticker, response):
        rows = [json.loads(r['exchange_order']) for r in self.rows(ticker) if r['exchange_order']]
        quantities = {side: sum((Decimal(o['fill_count_fp']) for o in rows if o['outcome_side'] == side),
                                Decimal(0)) for side in ('yes', 'no')}
        cost = sum((Decimal(o[k]) for o in rows for k in
                    ('taker_fill_cost_dollars', 'maker_fill_cost_dollars',
                     'taker_fees_dollars', 'maker_fees_dollars')), Decimal(0))
        reported_cost = sum((Decimal(response[k]) for k in
                             ('yes_total_cost_dollars', 'no_total_cost_dollars', 'fee_cost')), Decimal(0))
        if (response['ticker'] != ticker or response['exchange_index'] != 2
                or any(Decimal(response[s + '_count_fp']) != quantities[s] for s in ('yes', 'no'))
                or cost != reported_cost or not cost.is_finite()):
            raise RuntimeError('Demo settlement differs from tracked fills; review account activity')
        pnl = Decimal(response['revenue']) / 100 - cost
        self.db.execute('INSERT OR IGNORE INTO settlements VALUES (?,?,?)', (ticker, dumps(response), str(pnl)))
        self.db.commit()
