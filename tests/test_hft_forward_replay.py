import json
import sqlite3

from scripts.hft_forward_replay_029 import required_archive_bytes, select_segments


def catalog(path):
    db = sqlite3.connect(path)
    db.execute(
        """CREATE TABLE segments (
            id INTEGER PRIMARY KEY, status TEXT, count INTEGER, digest TEXT,
            previous_digest TEXT, stats TEXT, archive_key TEXT, archive_sha TEXT,
            archive_bytes INTEGER)"""
    )
    stats = json.dumps({"streams": [{"first_ns": 100, "last_ns": 200}]})
    db.execute(
        "INSERT INTO segments VALUES (1,'archived',2,'a','0',?,?,?,?)",
        (stats, "dataset/segment-1.jsonl.zst", "b", 12),
    )
    db.execute(
        "INSERT INTO segments VALUES (2,'archived',2,'c','a',?,?,?,?)",
        (json.dumps({"streams": [{"first_ns": 201, "last_ns": 300}]}), "dataset/segment-2.jsonl.zst", "d", 13),
    )
    db.commit()
    db.close()


def test_select_segments_uses_recorded_receipt_overlap(tmp_path):
    path = tmp_path / "catalog.sqlite3"
    catalog(path)
    rows = select_segments(path, 150, 250)
    assert [row["id"] for row in rows] == [1, 2]
    assert rows[0]["first_ns"] == 100
    assert rows[1]["last_ns"] == 300


def test_required_archive_bytes_sums_all_streams(tmp_path):
    path = tmp_path / "catalog.sqlite3"
    catalog(path)
    rows = select_segments(path, 100, 300)
    assert required_archive_bytes(rows, rows) == 50
