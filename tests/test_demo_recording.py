import hashlib
import json

import pytest

from demo_execution.recording import DemoRecording, archive_one
from research_lab.segments import archive_reader, catalog


class MemoryBucket:
    def __init__(self):
        self.objects = {}

    def put_verified(self, key, path):
        body = path.read_bytes()
        self.objects[key] = body
        return hashlib.sha256(body).hexdigest()


def sealed_recording(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_SEGMENT_EVENTS", "2")
    recording = DemoRecording(tmp_path, strategy="adaptive_volatility", source_sha256="a" * 64)
    recording.append("demo_start", {"revision": 1})
    recording.append("demo_rest", {"path": "/markets"})
    recording.commit()
    return recording


def test_demo_segments_archive_only_after_verified_upload(tmp_path, monkeypatch):
    recording = sealed_recording(tmp_path, monkeypatch)
    bucket = MemoryBucket()
    result = archive_one(tmp_path, bucket)
    assert result["state"] == "complete"
    assert result["segment"] == 0
    assert result["archive_sha256"] == checksum_bytes(bucket.objects[result["archive_key"]])

    c = catalog(tmp_path)
    row = c.execute("SELECT * FROM segments WHERE id=0").fetchone()
    assert row["status"] == "archived"
    assert not (tmp_path / row["path"]).exists()
    c.close()

    archive = tmp_path / "downloaded-archive"
    archive.write_bytes(bucket.objects[result["archive_key"]])
    with archive_reader(archive) as stream:
        lines = [json.loads(line) for line in stream]
    assert [line[3] for line in lines] == ["demo_recording_registration", "demo_start"]
    assert all(len(line) == 6 for line in lines)
    assert recording.active.events().__next__().kind == "segment_start"
    recording.close()


def test_demo_archive_failure_preserves_sealed_segment(tmp_path, monkeypatch):
    recording = sealed_recording(tmp_path, monkeypatch)

    class FailedBucket:
        def put_verified(self, key, path):
            raise OSError("unavailable")

    with pytest.raises(OSError, match="unavailable"):
        archive_one(tmp_path, FailedBucket())
    c = catalog(tmp_path)
    row = c.execute("SELECT * FROM segments WHERE id=0").fetchone()
    assert row["status"] == "sealed"
    assert (tmp_path / row["path"]).exists()
    assert not list(tmp_path.glob("archive-pending-*.jsonl.*"))
    c.close()
    recording.close()


def checksum_bytes(value):
    return hashlib.sha256(value).hexdigest()
