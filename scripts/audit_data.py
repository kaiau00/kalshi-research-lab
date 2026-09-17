"""Read-only, frozen-prefix data audit; never writes observations or runs strategies."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from research_lab.market import MarketState, epoch_ns
from research_lab.research import source_hash
from research_lab.storage import Store, canonical

NS = 10**9


def audit(path):
    store = Store(Path(path), readonly=True)
    prefix = store.prefix()
    state = MarketState()
    digest = '0' * 64
    counts, frames, latency = Counter(), Counter(), defaultdict(Counter)
    ticks, windows, metadata, sequences, cached = {}, {}, {}, {}, {}
    coverage = defaultdict(lambda: Counter())
    book_counts = defaultdict(Counter)
    first_meta, first_book, first_result = {}, {}, {}
    strikes, results = defaultdict(set), defaultdict(set)
    issues, gaps, sequence_issues = Counter(), [], []
    previous_ns, first_ns, last_ns, previous_id = 0, None, 0, 0
    registration = []
    source_missing = Counter()

    def flush(ticker, now):
        if ticker not in cached or ticker not in metadata:
            return
        then, at, valid, two_sided = cached[ticker]
        m = metadata[ticker]
        start, close = epoch_ns(m['open_time']), epoch_ns(m['close_time'])
        left, right = max(then, start), min(now, close)
        if right <= left:
            return
        if valid:
            coverage[ticker]['valid_ns'] += right - left
        if valid and two_sided:
            coverage[ticker]['two_sided_ns'] += right - left
            coverage[ticker]['fresh_two_sided_ns'] += max(0, min(right, at + 2 * NS) - left)

    def update_cache(ticker, now):
        book = state.books.get(ticker)
        if book:
            cached[ticker] = (now, book.at_ns, book.valid, bool(book.yes and book.no))

    for e in store.events(prefix['last_event_id']):
        first_ns = e.received_ns if first_ns is None else first_ns
        last_ns = e.received_ns
        if e.id != previous_id + 1:
            issues['noncontiguous_ids'] += 1
        if e.received_ns < previous_ns:
            issues['receipt_time_regressions'] += 1
        previous_ns, previous_id = e.received_ns, e.id
        digest = hashlib.sha256(bytes.fromhex(digest) + canonical(
            [e.received_ns, e.source_ns, e.kind, e.payload])).hexdigest()
        if digest != e.digest:
            raise ValueError(f'Hash mismatch at event {e.id}')
        counts[e.kind] += 1
        p = e.payload
        if e.kind == 'experiment_registration':
            registration.append({'event_id': e.id, 'source_matches': p['source_sha256'] == source_hash()})
        if e.kind == 'market':
            m = p['market']
            ticker = m['ticker']
            metadata[ticker] = m
            if m.get('floor_strike') is not None:
                strikes[ticker].add(str(Decimal(str(m['floor_strike']))))
                first_meta.setdefault(ticker, e.received_ns)
            if m.get('result'):
                results[ticker].add(m['result'])
                first_result.setdefault(ticker, e.received_ns)
        if e.kind == 'gap':
            gaps.append({'event_id': e.id, 'received_ns': e.received_ns, 'reason': p.get('reason')})
        frame = p.get('frame', {}) if e.kind == 'ws' else {}
        typ, msg = frame.get('type'), frame.get('msg') or {}
        ticker = msg.get('market_ticker')
        if typ:
            frames[typ] += 1
            if 'sid' in frame and 'seq' in frame:
                key, seq = (p['session'], frame['sid']), frame['seq']
                prev = sequences.get(key)
                if prev is not None and seq != prev + 1:
                    sequence_issues.append({'event_id': e.id, 'type': typ, 'previous': prev, 'current': seq})
                sequences[key] = seq
            if e.source_ns is None:
                source_missing[typ] += 1
            else:
                ms = (e.received_ns - e.source_ns) / 1e6
                bucket = ('negative' if ms < -100 else '<=250ms' if ms <= 250 else
                          '<=1s' if ms <= 1000 else '<=3s' if ms <= 3000 else '<=10s' if ms <= 10000 else '>10s')
                latency[typ][bucket] += 1
            if typ == 'cfbenchmarks_value' and msg.get('index_id') == 'BRTI':
                raw = msg['data']
                data = json.loads(raw) if isinstance(raw, str) else raw
                sec, price = int(data['time']) // 1000, Decimal(str(data['value']))
                if e.source_ns != int(data['time']) * 1_000_000:
                    issues['benchmark_source_timestamp_mismatch'] += 1
                if sec in ticks:
                    issues['duplicate_benchmark_seconds'] += 1
                    if ticks[sec][0] != price:
                        issues['conflicting_benchmark_seconds'] += 1
                else:
                    ticks[sec] = (price, e.received_ns)
                window = msg.get('last_60s_windowed_average_15min')
                if window and sec % 900 == 0:
                    windows[sec] = window
            if typ in ('orderbook_snapshot', 'orderbook_delta'):
                book_counts[ticker][typ] += 1
                first_book.setdefault(ticker, e.received_ns)
                if typ == 'orderbook_snapshot' and not msg.get('yes_dollars_fp') and not msg.get('no_dollars_fp'):
                    book_counts[ticker]['empty_snapshots'] += 1
        old_quality = state.quality.copy()
        # Cache previous book state before apply mutates it, including global invalidations.
        state.apply(e)
        invalidated = state.quality != old_quality or e.kind == 'gap'
        affected = list(cached) if invalidated else ([ticker] if typ in ('orderbook_snapshot', 'orderbook_delta') else [])
        for t in affected:
            flush(t, e.received_ns)
            update_cache(t, e.received_ns)
        if ticker and typ in ('orderbook_snapshot', 'orderbook_delta') and ticker not in cached:
            update_cache(ticker, e.received_ns)
    for ticker in cached:
        flush(ticker, last_ns)
    rows = []
    for ticker, m in sorted(metadata.items(), key=lambda item: item[1]['close_time']):
        start, close = epoch_ns(m['open_time']) // NS, epoch_ns(m['close_time']) // NS
        targets = list(range(close - 60, close))
        missing = [sec for sec in targets if sec not in ticks]
        average = sum((ticks[sec][0] for sec in targets if sec in ticks), Decimal(0)) / 60 if not missing else None
        rounded = average.quantize(Decimal('.01'), rounding=ROUND_HALF_UP) if average is not None else None
        observed = [sec for sec in range(start + 1, close + 1) if sec in ticks]
        missing_all = [sec for sec in range(start + 1, close + 1) if sec not in ticks]
        threshold = m.get('floor_strike')
        expected = None
        if rounded is not None and threshold is not None:
            d = Decimal(str(threshold))
            expected = 'yes' if (rounded >= d if m['strike_type'] == 'greater_or_equal' else rounded > d) else 'no'
        row = {k: m.get(k) for k in ('ticker', 'open_time', 'close_time', 'floor_strike', 'strike_type',
                                    'custom_strike', 'status', 'result', 'expiration_value')}
        row.update({
            'metadata_supported': state.metadata(ticker) is not None,
            'threshold_versions': sorted(strikes[ticker]), 'result_versions': sorted(results[ticker]),
            'threshold_first_seen_seconds_after_open': (first_meta[ticker] / NS - start) if ticker in first_meta else None,
            'book_first_seen_seconds_after_open': (first_book[ticker] / NS - start) if ticker in first_book else None,
            'result_first_seen_seconds_after_close': (first_result[ticker] / NS - close) if ticker in first_result else None,
            'recording_spans_market': first_ns <= start * NS and last_ns >= close * NS,
            'benchmark_seconds_present': len(observed), 'benchmark_seconds_expected': close - start,
            'missing_benchmark_seconds': missing_all,
            'final_minute_count': 60 - len(missing), 'final_minute_missing_seconds': missing,
            'reconstructed_settlement': str(rounded) if rounded is not None else None,
            'unrounded_average': str(average) if average is not None else None,
            'recorded_settlement_matches': rounded == Decimal(m['expiration_value']) if rounded is not None and m.get('expiration_value') else None,
            'reconstructed_result': expected,
            'recorded_result_matches': expected == m['result'] if expected and m.get('result') else None,
            'exchange_final_window': windows.get(close),
            'book_counts': dict(book_counts[ticker]),
            'book_coverage_seconds': {k.removesuffix('_ns'): v / NS for k, v in coverage[ticker].items()},
        })
        rows.append(row)
    output = {'schema_version': 2, 'settlement_window': '[close-60s, close)', 'scope': 'Data integrity and coverage only; no strategy or execution validation',
              'database': str(path), 'prefix': prefix, 'verified_events': previous_id,
              'hash_matches_frozen_prefix': digest == prefix['sha256_chain'],
              'first_received_ns': first_ns, 'last_received_ns': last_ns,
              'counts': dict(counts), 'frame_counts': dict(frames), 'registration': registration,
              'normalizer_quality': state.quality, 'issues': dict(issues), 'gaps': gaps,
              'sequence_issues': sequence_issues, 'source_timestamp_missing': dict(source_missing),
              'source_to_receipt_latency': {k: dict(v) for k, v in latency.items()}, 'markets': rows}
    store.close()
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.db), indent=2))
