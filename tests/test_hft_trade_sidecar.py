import hashlib
import json

import pytest
from fastapi.testclient import TestClient

import demo_execution.app as app_module
from hft_research.archive import process_trade_segment
from hft_research.provenance import TRADE_TAPE_FORMAT
from hft_research.registration import registration_hash
from hft_research.sidecar import TradeTapeSidecar, advance_sequence
from research_lab.segments import archive_reader, catalog, checksum, restore
from research_lab.storage import Store


class MemoryBucket:
    def __init__(self):
        self.objects = {}
        self.fail_manifest = False

    def put_verified(self, key, path):
        if self.fail_manifest and key.endswith("manifest.json"):
            raise OSError("manifest unavailable")
        body = path.read_bytes()
        self.objects[key] = body
        return hashlib.sha256(body).hexdigest()

    def get(self, key, path, expected):
        path.write_bytes(self.objects[key])
        if checksum(path) != expected:
            raise ValueError("Downloaded archive checksum mismatch")


def trade_frame(ticker="KXBTC15M-TEST", trade_id="trade-1", block=False):
    return {
        "type": "trade",
        "sid": 7,
        "seq": 4,
        "msg": {
            "trade_id": trade_id,
            "market_ticker": ticker,
            "yes_price_dollars": "0.4200",
            "no_price_dollars": "0.5800",
            "count_fp": "3.00",
            "taker_outcome_side": "yes",
            "taker_book_side": "ask",
            "is_block_trade": block,
            "ts_ms": 1669149841000,
        },
    }


def make_sidecar(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_SEGMENT_EVENTS", "500")
    monkeypatch.setenv("LAB_SEGMENT_SECONDS", "1800")
    return TradeTapeSidecar(tmp_path, lambda: {"KXBTC15M-TEST"})


def test_trade_sidecar_registration_scope_and_raw_frame(tmp_path, monkeypatch):
    sidecar = make_sidecar(tmp_path, monkeypatch)
    first = next(sidecar.store.active.events())
    assert first.kind == "hft_trade_registration"
    assert first.payload["format"] == TRADE_TAPE_FORMAT
    assert first.payload["study_registration_sha256"] == registration_hash()
    assert first.payload["production_orders_authorized"] is False

    event = sidecar.record_frame(trade_frame(), "session-1", {"KXBTC15M-TEST"})
    sidecar.store.commit()
    assert event.kind == "ws"
    assert event.source_ns == 1669149841000 * 1_000_000
    assert event.payload["frame"]["msg"]["count_fp"] == "3.00"
    assert sidecar.status["trade_messages"] == 1
    assert sidecar.status["non_block_trade_messages"] == 1
    assert sidecar.status["block_trade_messages"] == 0
    sidecar.store.close()


def test_trade_sidecar_rejects_scope_sequence_gap_and_hot_limit(tmp_path, monkeypatch):
    sidecar = make_sidecar(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="escaped"):
        sidecar.watch_provider = lambda: {"OTHER-TEST"}
        sidecar.watch()
    assert advance_sequence(None, {"sid": 7, "seq": 4}, 7) == 4
    with pytest.raises(RuntimeError, match="sequence_gap"):
        advance_sequence(4, {"sid": 7, "seq": 6}, 7)
    sidecar.max_bytes = 1
    with pytest.raises(RuntimeError, match="hot_storage_limit"):
        sidecar._check_capacity()
    sidecar.store.close()


def test_trade_archive_manifest_retry_restore_and_cap(tmp_path, monkeypatch):
    sidecar = make_sidecar(tmp_path, monkeypatch)
    sidecar.record_frame(trade_frame(), "session-1", {"KXBTC15M-TEST"})
    sidecar.store.seal()
    bucket = MemoryBucket()
    bucket.fail_manifest = True
    with pytest.raises(OSError, match="manifest unavailable"):
        process_trade_segment(tmp_path, bucket)
    cat = catalog(tmp_path)
    row = cat.execute("SELECT * FROM segments WHERE id=0").fetchone()
    assert row["status"] == "sealed"
    assert (tmp_path / row["path"]).exists()
    cat.close()

    bucket.fail_manifest = False
    result = process_trade_segment(tmp_path, bucket)
    assert result["state"] == "complete"
    assert result["archive_key"].startswith("hft-trades-v1/")
    manifest_key = result["archive_key"].rsplit("/", 1)[0] + "/manifest.json"
    manifest = json.loads(bucket.objects[manifest_key])
    assert manifest["segments"][0]["digest"] == result["digest"]

    archive = tmp_path / "inspect.zst"
    archive.write_bytes(bucket.objects[result["archive_key"]])
    with archive_reader(archive) as stream:
        lines = [json.loads(line) for line in stream]
    assert [line[3] for line in lines] == ["hft_trade_registration", "ws"]
    assert all(len(line) == 6 for line in lines)

    restored = tmp_path / "restored.sqlite3"
    verified = restore(tmp_path, restored, bucket)
    assert verified["verified_events"] == 2
    read = Store(restored, readonly=True)
    assert [event.kind for event in read.events()] == ["hft_trade_registration", "ws"]
    read.close()
    sidecar.store.close()

    capped_root = tmp_path / "capped"
    capped = make_sidecar(capped_root, monkeypatch)
    capped.record_frame(trade_frame(), "session-2", {"KXBTC15M-TEST"})
    capped.store.seal()
    monkeypatch.setenv("LAB_HFT_TRADE_ARCHIVE_MAX_BYTES", "1")
    with pytest.raises(ValueError, match="budget"):
        process_trade_segment(capped_root, MemoryBucket())
    cap_cat = catalog(capped_root)
    cap_row = cap_cat.execute("SELECT * FROM segments WHERE id=0").fetchone()
    assert cap_row["status"] == "sealed"
    assert (capped_root / cap_row["path"]).exists()
    cap_cat.close()
    capped.store.close()


def test_registration_change_refuses_existing_dataset(tmp_path, monkeypatch):
    sidecar = make_sidecar(tmp_path, monkeypatch)
    sidecar.store.close()
    cat = catalog(tmp_path)
    cat.execute("UPDATE settings SET value=? WHERE key='source_sha256'", ("0" * 64,))
    cat.commit()
    cat.close()
    with pytest.raises(RuntimeError, match="registration changed"):
        make_sidecar(tmp_path, monkeypatch)


def test_sidecar_start_failure_does_not_abort_shared_app(monkeypatch):
    def fail_start(*args, **kwargs):
        raise RuntimeError("isolated sidecar failure")

    monkeypatch.setenv("LAB_HFT_TRADE_TAPE_ENABLED", "1")
    monkeypatch.setenv("LAB_DASHBOARD_PASSWORD", "test-password-long-enough")
    monkeypatch.setattr(app_module, "TradeTapeSidecar", fail_start)
    with TestClient(app_module.create_app(record=False)) as client:
        response = client.get(
            "/api/hft-trade-tape/status",
            auth=("lab", "test-password-long-enough"),
        )
        assert response.json()["state"] == "failed"
        assert "isolated sidecar failure" in response.json()["error"]
        assert client.get("/healthz").status_code == 200
