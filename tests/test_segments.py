import json
import shutil

import pytest
from test_engine import prepared

from research_lab.checkpoint import decode, encode
from research_lab.demo import create_demo
from research_lab.engine import Replay
from research_lab.research import source_hash
from research_lab.segments import SegmentedStore, checksum, process_one, restore
from research_lab.settings import Experiment
from research_lab.storage import Store


class FakeBucket:
    def __init__(self, root):
        self.root = root
        self.fail = False

    def put_verified(self, key, path):
        if self.fail:
            raise OSError('simulated failed upload')
        dest = self.root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        assert checksum(dest) == checksum(path)
        return checksum(path)

    def get(self, key, path, expected):
        shutil.copyfile(self.root / key, path)
        if checksum(path) != expected:
            raise ValueError('Downloaded archive checksum mismatch')


def test_checkpoint_preserves_pending_order_aliases_and_reservations():
    original, ticker, account, now = prepared()
    copy = decode(json.loads(json.dumps(encode(original))))
    a = copy.accounts[account.name]
    assert a.pending[ticker] is a.orders[0]
    assert a.reserved == account.reserved
    original._fill_due(account, now + 500_000_000)
    copy._fill_due(a, now + 500_000_000)
    assert copy.results() == original.results()
    assert a.positions[ticker] is a.orders[0]


def test_segment_archive_retry_restore_and_continuous_accounts(tmp_path, monkeypatch):
    monkeypatch.setenv('LAB_SEGMENT_EVENTS', '500')
    root = tmp_path / 'live'
    writer = SegmentedStore(root)
    writer.append('experiment_registration', {'config': Experiment().to_dict(), 'source_sha256': source_hash()},
                  received_ns=1799999998 * 10**9)
    demo = tmp_path / 'demo.db'
    create_demo(demo, markets=2)
    source = Store(demo, readonly=True)
    for e in source.events():
        writer.append(e.kind, e.payload, received_ns=e.received_ns, source_ns=e.source_ns)
    source.close()
    writer.seal()
    expected = Replay()
    rows = list(writer.cat.execute("SELECT * FROM segments WHERE status='sealed' ORDER BY id"))
    for row in rows:
        s = Store(root / row['path'], readonly=True)
        for e in s.events():
            expected.feed(e)
        s.close()
    bucket = FakeBucket(tmp_path / 'bucket')
    bucket.fail = True
    with pytest.raises(OSError):
        process_one(root, bucket)
    assert (root / rows[0]['path']).exists()  # No deletion on failed upload.
    cp = json.loads((root / 'checkpoint.json').read_text())
    assert cp['data']['next_segment'] == 1
    bucket.fail = False
    for _ in rows:
        assert process_one(root, bucket)['state'] == 'complete'
    assert process_one(root, bucket)['state'] == 'idle'
    cp = json.loads((root / 'checkpoint.json').read_text())
    actual = decode(cp['data']['replay'])
    assert actual.results() == expected.results()
    assert not any((root / row['path']).exists() for row in rows)
    restored = tmp_path / 'restored.db'
    verified = restore(root, restored, bucket)
    assert verified['verified_events'] == expected.event_count
    replay = Replay()
    read = Store(restored, readonly=True)
    for e in read.events():
        replay.feed(e)
    assert replay.results() == expected.results()
    read.close()
    writer.close()
    again = SegmentedStore(root)
    assert again.prefix()['last_event_id'] > expected.event_count
    again.close()
    # A tampered checkpoint fails before touching archives or resetting accounts.
    cp['data']['source'] = 'bad'
    (root / 'checkpoint.json').write_text(json.dumps(cp))
    first_archive = next((tmp_path / 'bucket').rglob('segment-*.gz'))
    first_archive.write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='checksum'):
        restore(root, tmp_path / 'bad-restore.db', bucket)
