"""Bounded hot SQLite segments, verified cold archives, continuous paper checkpoints."""
from __future__ import annotations

import fcntl
import gzip
import hashlib
import io
import json
import os
import shutil
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import zstandard

from .checkpoint import decode, encode
from .engine import Replay
from .research import LIMITATIONS, render_report, source_compatible, source_hash, write_json
from .settings import Experiment
from .storage import Event, Store, canonical


def catalog(root):
    c = sqlite3.connect(Path(root) / 'catalog.sqlite3', timeout=10)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA synchronous=FULL')
    c.executescript('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS segments (id INTEGER PRIMARY KEY, path TEXT NOT NULL,
        status TEXT NOT NULL, count INTEGER DEFAULT 0, digest TEXT, previous_digest TEXT,
        stats TEXT, archive_key TEXT, archive_sha TEXT, archive_bytes INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS markets (ticker TEXT PRIMARY KEY, payload TEXT NOT NULL);''')
    c.commit()
    return c


def checksum(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def durable_json(path, value):
    path = Path(path)
    temp = path.with_suffix('.tmp')
    with temp.open('wb') as f:
        f.write(canonical(value))
        f.flush()
        os.fsync(f.fileno())
    temp.replace(path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def archive_gzip_level():
    return min(9, max(1, int(os.environ.get('LAB_ARCHIVE_GZIP_LEVEL', '6'))))


def archive_format():
    value = os.environ.get('LAB_ARCHIVE_COMPRESSION', 'zstd').lower()
    if value not in {'gzip', 'zstd'}:
        raise ValueError('LAB_ARCHIVE_COMPRESSION must be gzip or zstd')
    return value


def archive_zstd_level():
    return min(22, max(1, int(os.environ.get('LAB_ARCHIVE_ZSTD_LEVEL', '9'))))


def archive_suffix():
    return '.jsonl.zst' if archive_format() == 'zstd' else '.jsonl.gz'


@contextmanager
def archive_writer(path):
    """Write the configured raw archive format; checkpoints remain gzip."""
    if archive_format() == 'gzip':
        with gzip.open(path, 'wb', compresslevel=archive_gzip_level()) as stream:
            yield stream
        return
    with Path(path).open('wb') as raw:
        with zstandard.ZstdCompressor(level=archive_zstd_level()).stream_writer(
                raw, closefd=False) as stream:
            yield stream


@contextmanager
def archive_reader(path):
    """Read gzip or Zstandard by magic bytes, independent of a temporary filename."""
    path = Path(path)
    with path.open('rb') as probe:
        magic = probe.read(4)
    if magic.startswith(b'\x1f\x8b'):
        with gzip.open(path, 'rt') as stream:
            yield stream
        return
    if magic == b'\x28\xb5\x2f\xfd':
        with path.open('rb') as raw:
            with zstandard.ZstdDecompressor().stream_reader(raw, closefd=False) as decoded:
                with io.TextIOWrapper(decoded) as stream:
                    yield stream
        return
    raise ValueError('Unknown archive compression format')


def remove_segment_artifacts(path):
    """Remove only disposable local replicas after their archive is verified."""
    path = Path(path)
    for artifact in (path, Path(str(path) + '-wal'), Path(str(path) + '-shm'),
                     Path(str(path) + '.lock')):
        artifact.unlink(missing_ok=True)


def cleanup_archived_artifacts(root, cat):
    for row in cat.execute("SELECT path FROM segments WHERE status='archived'"):
        remove_segment_artifacts(Path(root) / row['path'])


class SegmentedStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = (self.root / 'recording.lock').open('a')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.cat = catalog(root)
        # Older releases removed the database but left its empty lock/WAL/SHM
        # sidecars. Archived rows prove those local replicas are disposable.
        cleanup_archived_artifacts(self.root, self.cat)
        row = self.cat.execute("SELECT value FROM settings WHERE key='dataset'").fetchone()
        self.dataset = row[0] if row else uuid.uuid4().hex
        self.cat.execute("INSERT OR IGNORE INTO settings VALUES('dataset',?)", (self.dataset,))
        self.cat.commit()
        self.limit = int(os.environ.get('LAB_SEGMENT_EVENTS', '500000'))
        self.seconds = int(os.environ.get('LAB_SEGMENT_SECONDS', '1800'))
        self._bytes_cache = None
        self._bytes_checked = 0.0
        row = self.cat.execute("SELECT * FROM segments WHERE status='open'").fetchone()
        if row:
            self.segment = row['id']
            self.active = Store(self.root / row['path'])
        else:
            self._new()
        self.started = time.monotonic()

    def _new(self):
        last = self.cat.execute('SELECT * FROM segments ORDER BY id DESC LIMIT 1').fetchone()
        self.segment = last['id'] + 1 if last else 0
        previous = last['digest'] if last else '0' * 64
        path = f'segment-{self.segment:08d}.sqlite3'
        self.cat.execute('INSERT INTO segments(id,path,status,previous_digest) VALUES(?,?,?,?)',
                         (self.segment, path, 'open', previous))
        self.cat.commit()
        self.active = Store(self.root / path)
        if self.segment:
            self.active.append('segment_start', {'dataset': self.dataset, 'segment': self.segment,
                                                'previous_digest': previous}, received_ns=max(x['last_ns'] for x in json.loads(last['stats'])['streams']))
        self.started = time.monotonic()

    def seal(self):
        if not self.active.prefix()['last_event_id']:
            return
        self.commit()
        stats = self.active.stats()
        self.active.close()
        self.cat.execute("UPDATE segments SET status='sealed',count=?,digest=?,stats=? WHERE id=?",
                         (stats['prefix']['last_event_id'], stats['prefix']['sha256_chain'], json.dumps(stats), self.segment))
        self.cat.commit()
        self._new()

    def append(self, kind, payload, *, source_ns=None, received_ns=None):
        if self.active.prefix()['last_event_id'] >= self.limit or time.monotonic() - self.started >= self.seconds:
            self.seal()
        event = self.active.append(kind, payload, source_ns=source_ns, received_ns=received_ns)
        if kind == 'market':
            self.cat.execute('INSERT OR REPLACE INTO markets VALUES(?,?)',
                             (payload['market']['ticker'], json.dumps(payload['market'])))
        return event

    def latest_markets(self):
        return [json.loads(row[0]) for row in self.cat.execute('SELECT payload FROM markets')]

    def commit(self):
        self.active.commit()
        self.cat.commit()

    def prefix(self):
        sealed = self.cat.execute("SELECT COALESCE(SUM(count),0) FROM segments WHERE status!='open'").fetchone()[0]
        p = self.active.prefix()
        return {'last_event_id': sealed + p['last_event_id'], 'sha256_chain': p['sha256_chain'], 'segment': self.segment}

    def stats(self):
        now = time.monotonic()
        if self._bytes_cache is None or now - self._bytes_checked >= 30:
            self._bytes_cache = sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())
            self._bytes_checked = now
        return {'prefix': self.prefix(), 'bytes': self._bytes_cache,
                'streams': self.active.stats()['streams'], 'dataset': self.dataset,
                'sealed_segments': self.cat.execute("SELECT COUNT(*) FROM segments WHERE status='sealed'").fetchone()[0],
                'archived_segments': self.cat.execute("SELECT COUNT(*) FROM segments WHERE status='archived'").fetchone()[0],
                'archive_bytes': self.cat.execute('SELECT COALESCE(SUM(archive_bytes),0) FROM segments').fetchone()[0]}

    def has_sealed(self):
        return self.cat.execute("SELECT 1 FROM segments WHERE status='sealed' LIMIT 1").fetchone() is not None

    def close(self):
        self.commit()
        self.active.close()
        self.cat.close()
        self.lock.close()


class Bucket:
    def __init__(self):
        import boto3
        from botocore.config import Config
        self.name = os.environ['LAB_ARCHIVE_BUCKET']
        self.client = boto3.client('s3', endpoint_url=os.environ['LAB_ARCHIVE_ENDPOINT'],
            aws_access_key_id=os.environ['LAB_ARCHIVE_ACCESS_KEY'], aws_secret_access_key=os.environ['LAB_ARCHIVE_SECRET_KEY'],
            region_name=os.environ.get('LAB_ARCHIVE_REGION', 'auto'),
            config=Config(s3={'addressing_style': os.environ.get('LAB_ARCHIVE_STYLE', 'virtual')},
                          connect_timeout=10, read_timeout=30, retries={'max_attempts': 2}))

    def put_verified(self, key, path):
        expected = checksum(path)
        with Path(path).open('rb') as body:
            self.client.put_object(Bucket=self.name, Key=key, Body=body, Metadata={'sha256': expected})
        # HEAD metadata alone cannot prove payload integrity. Read every uploaded byte back.
        response = self.client.get_object(Bucket=self.name, Key=key)
        h = hashlib.sha256()
        try:
            for block in response['Body'].iter_chunks(1024 * 1024):
                h.update(block)
        finally:
            response['Body'].close()
        if h.hexdigest() != expected:
            raise ValueError('Archive read-back checksum mismatch')
        return expected

    def get(self, key, path, expected):
        self.client.download_file(self.name, key, str(path))
        if checksum(path) != expected:
            raise ValueError('Downloaded archive checksum mismatch')


def archive_events(path, row):
    digest = '0' * 64
    count = 0
    with archive_reader(path) as f:
        for line in f:
            fields = json.loads(line)
            if len(fields) not in (5, 6):
                raise ValueError("Unknown archive envelope")
            i, received, source, kind, payload = fields[:5]
            recorded_digest = fields[5] if len(fields) == 6 else None
            if i != count + 1:
                raise ValueError('Archive event ordering error')
            digest = hashlib.sha256(bytes.fromhex(digest) + canonical([received, source, kind, payload])).hexdigest()
            if recorded_digest is not None and digest != recorded_digest:
                raise ValueError('Archive event integrity error')
            count += 1
            yield Event(i, received, source, kind, payload, digest)
    if count != row['count'] or digest != row['digest']:
        raise ValueError('Archive prefix mismatch')


def process_one(root, bucket=None):
    root = Path(root)
    with (root / 'processing.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _process_one(root, bucket)


def _process_one(root, bucket):
    cat = catalog(root)
    try:
        row = cat.execute("SELECT * FROM segments WHERE status='sealed' ORDER BY id LIMIT 1").fetchone()
        if row is None:
            return {'state': 'idle'}
        row = dict(row)
        dataset = cat.execute("SELECT value FROM settings WHERE key='dataset'").fetchone()[0]
        checkpoint = root / 'checkpoint.json'
        replay, next_segment = Replay(), 0
        registered_source = source_hash()
        if checkpoint.exists():
            envelope = json.loads(checkpoint.read_text())
            data = envelope['data']
            if hashlib.sha256(canonical(data)).hexdigest() != envelope['sha256']:
                raise ValueError('Checkpoint checksum mismatch')
            if not source_compatible(data['source']) or data['dataset'] != dataset:
                raise ValueError('Checkpoint source/dataset mismatch')
            registered_source = data['source']
            replay, next_segment = decode(data['replay']), data['next_segment']
            if replay.cfg.to_dict() != Experiment().to_dict():
                raise ValueError('Checkpoint experiment mismatch')
        if next_segment == row['id'] and next_segment and data['last_digest'] != row['previous_digest']:
            raise ValueError('Checkpoint predecessor mismatch')
        if next_segment > row['id'] + 1:
            raise ValueError('Checkpoint is ahead of an unarchived predecessor')
        if next_segment < row['id']:
            raise ValueError('Missing predecessor checkpoint')
        store = Store(root / row['path'], readonly=True)
        try:
            if row['count'] > int(os.environ.get('LAB_SEGMENT_EVENTS', '500000')) + 1:
                raise ValueError('Segment exceeds bounded processing limit')
            output = root / ('archive-pending' + archive_suffix())
            digest = '0' * 64
            with archive_writer(output) as f:
                for e in store.events(row['count']):
                    digest = hashlib.sha256(bytes.fromhex(digest) + canonical(
                        [e.received_ns, e.source_ns, e.kind, e.payload])).hexdigest()
                    if digest != e.digest:
                        raise ValueError('Segment hash mismatch')
                    if e.id == 1:
                        if row['id'] == 0:
                            registered_source = e.payload.get('source_sha256')
                            if (e.kind != 'experiment_registration' or not source_compatible(registered_source)
                                    or e.payload.get('config') != replay.cfg.to_dict()):
                                raise ValueError('Missing matching forward registration')
                        elif (e.kind != 'segment_start' or e.payload.get('dataset') != dataset
                              or e.payload.get('previous_digest') != row['previous_digest']):
                            raise ValueError('Broken segment linkage')
                    if next_segment == row['id']:
                        replay.feed(e)
                    f.write(canonical([e.id, e.received_ns, e.source_ns, e.kind, e.payload]) + b'\n')
            if digest != row['digest']:
                raise ValueError('Sealed prefix mismatch')
        finally:
            store.close()
        data = {'source': registered_source, 'dataset': dataset, 'next_segment': row['id'] + 1,
                'last_digest': digest, 'replay': encode(replay)}
        if len(canonical(data)) > 50_000_000:
            raise ValueError('Checkpoint capacity reached')
        if next_segment == row['id']:
            durable_json(checkpoint, {'data': data, 'sha256': hashlib.sha256(canonical(data)).hexdigest()})
        out = root / 'reports'
        out.mkdir(exist_ok=True)
        interval = max(0, int(os.environ.get('LAB_REPORT_INTERVAL_SECONDS', '3600')))
        existing_reports = sorted(out.glob('*.json'))
        due = (not existing_reports or interval == 0
               or time.time() - existing_reports[-1].stat().st_mtime >= interval)
        name = None
        if due:
            report = replay.results()
            report['manifest'] = {'config': replay.cfg.to_dict(), 'split': 'forward',
                                  'source_sha256': registered_source,
                                  'dataset': dataset, 'last_segment': row['id'], 'last_digest': digest,
                                  'limitations': LIMITATIONS, 'incremental': True,
                                  'selection_warning': 'Fixed prospective settings; no holdout claim or parameter tuning.'}
            name = f'{time.time_ns()}-{uuid.uuid4().hex[:8]}'
            write_json(out / (name + '.json'), report)
            (out / (name + '.html')).write_text(render_report(report))
            for old in sorted(out.glob('*.json'))[:-5]:
                old.unlink()
                old.with_suffix('.html').unlink(missing_ok=True)
        used = cat.execute('SELECT COALESCE(SUM(archive_bytes),0) FROM segments').fetchone()[0]
        if used + output.stat().st_size > int(os.environ.get('LAB_ARCHIVE_MAX_BYTES', '20000000000')):
            raise ValueError('Archive budget capacity reached; preserve local data and stop')
        bucket = bucket or Bucket()
        key = f'{dataset}/segment-{row["id"]:08d}-{digest}{archive_suffix()}'
        sha = bucket.put_verified(key, output)
        # Keep a recovery checkpoint alongside each archive; catalog is recoverable from segment headers.
        checkpoint_every = max(1, int(os.environ.get('LAB_REMOTE_CHECKPOINT_EVERY_SEGMENTS', '4')))
        checkpoint_uploaded = row['id'] % checkpoint_every == 0
        cp_path = root / 'checkpoint-upload.json.gz'
        if checkpoint_uploaded:
            with gzip.open(cp_path, 'wb', compresslevel=archive_gzip_level()) as f:
                f.write(checkpoint.read_bytes())
            slot = (row['id'] // checkpoint_every) % 2
            bucket.put_verified(f'{dataset}/checkpoint-slot-{slot}.json.gz', cp_path)
        cat.execute("UPDATE segments SET status='archived',archive_key=?,archive_sha=?,archive_bytes=? WHERE id=?",
                    (key, sha, output.stat().st_size, row['id']))
        cat.commit()
        # The raw segment is remotely verified; the current checkpoint remains durable on the volume.
        remove_segment_artifacts(root / row['path'])
        output.unlink()
        cp_path.unlink(missing_ok=True)
        return {'state': 'complete', 'segment': row['id'],
                'report': name + '.json' if name else None,
                'events_replayed': replay.event_count, 'archive_sha256': sha,
                'checkpoint_uploaded': checkpoint_uploaded}
    finally:
        cat.close()


def restore(root, destination, bucket=None):
    with (Path(root) / "processing.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _restore(root, destination, bucket)


def _restore(root, destination, bucket=None):
    """Restore all sealed segments to a new SQLite store; never overwrite originals."""
    root, destination = Path(root), Path(destination)
    if destination.exists():
        raise ValueError('Refusing to overwrite restored data')
    cat = catalog(root)
    target = Store(destination)
    previous = '0' * 64
    try:
        for row in cat.execute("SELECT * FROM segments WHERE status!='open' ORDER BY id"):
            if row['previous_digest'] != previous:
                raise ValueError('Catalog linkage mismatch')
            if row['status'] == 'archived':
                bucket = bucket or Bucket()
                temp = destination.with_suffix('.download.gz')
                bucket.get(row['archive_key'], temp, row['archive_sha'])
                events = archive_events(temp, row)
                source = None
            else:
                source = Store(root / row['path'], readonly=True)
                if source.verify()['sha256_chain'] != row['digest']:
                    raise ValueError('Hot segment mismatch')
                events = source.events(row['count'])
            try:
                for e in events:
                    target.append(e.kind, e.payload, received_ns=e.received_ns, source_ns=e.source_ns)
                target.commit()
            finally:
                if source:
                    source.close()
                else:
                    temp.unlink(missing_ok=True)
            previous = row['digest']
        return target.verify()
    finally:
        target.close()
        cat.close()


def enough_disk(root):
    return shutil.disk_usage(root).free >= 300_000_000
