import sqlite3

import pytest

from research_lab.storage import Store


def test_frozen_prefix_integrity_and_clock_regression(tmp_path):
    path = tmp_path / 'raw.db'
    writer = Store(path)
    writer.append('test', {'value': 1}, received_ns=100)
    writer.commit()
    reader = Store(path, readonly=True)
    end = reader.prefix()['last_event_id']
    writer.append('test', {'value': 2}, received_ns=90)
    writer.commit()
    assert len(list(reader.events(end))) == 1
    assert reader.verify()['verified_events'] == 2
    event = list(reader.events())[-1]
    assert event.received_ns == 100
    assert event.payload['_clock_adjustment_received_ns'] == 90
    with pytest.raises(RuntimeError):
        reader.append('bad', {})
    with pytest.raises(RuntimeError, match='Another recorder'):
        Store(path)
    reader.close()
    writer.close()
    conn = sqlite3.connect(path)
    conn.execute("UPDATE events SET source_ns=42 WHERE id=1")
    conn.commit()
    conn.close()
    reader = Store(path, readonly=True)
    with pytest.raises(ValueError, match='hash mismatch'):
        reader.verify()
    reader.close()


def test_restart_keeps_hash_chain(tmp_path):
    path = tmp_path / 'raw.db'
    for i in range(2):
        store = Store(path)
        store.append('test', {'i': i})
        store.close()
    store = Store(path, readonly=True)
    assert store.verify()['verified_events'] == 2
    store.close()


def test_backup_includes_committed_wal_and_restores(tmp_path):
    path = tmp_path / 'raw.db'
    writer = Store(path)
    writer.append('test', {'value': 1})
    writer.commit()
    reader = Store(path, readonly=True)
    result = reader.backup(tmp_path / 'backup.db')
    assert result == reader.verify()
    writer.append('test', {'value': 2})
    writer.commit()
    backup = Store(tmp_path / 'backup.db', readonly=True)
    assert backup.verify()['verified_events'] == 1
    backup.close()
    reader.close()
    writer.close()
