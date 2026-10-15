import asyncio
import base64

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from historical_archive.downloader import (
    Acquisition,
    ArchiveClient,
    benchmark_hours,
    candle_batches,
    parse_utc,
)


def market(i, start, close):
    return {
        "ticker": f"KXBTC15M-TEST-{i}",
        "event_ticker": f"KXBTC15M-TESTEVENT-{i}",
        "open_time": f"2026-01-01T{start}:00Z",
        "close_time": f"2026-01-01T{close}:00Z",
        "result": "yes",
    }


def test_parse_utc_date_and_timestamp():
    assert parse_utc("2026-01-01") == 1767225600
    assert parse_utc("2026-01-01T01:00:00+01:00") == 1767225600


def test_candle_batches_stay_under_request_limit():
    rows = []
    for index in range(96):
        start_minutes = index * 15
        close_minutes = start_minutes + 15
        rows.append(
            {
                "ticker": f"KXBTC15M-TEST-{index}",
                "event_ticker": f"KXBTC15M-TESTEVENT-{index}",
                "open_time": f"2026-01-{1 + start_minutes // 1440:02d}T{(start_minutes // 60) % 24:02d}:{start_minutes % 60:02d}:00Z",
                "close_time": f"2026-01-{1 + close_minutes // 1440:02d}T{(close_minutes // 60) % 24:02d}:{close_minutes % 60:02d}:00Z",
                "result": "yes",
            }
        )
    batches = candle_batches(rows)
    assert [item["ticker"] for batch in batches for item in batch] == [item["ticker"] for item in rows]
    assert all(len(batch) <= 100 for batch in batches)
    for batch in batches:
        start = min(parse_utc(item["open_time"]) for item in batch)
        end = max(parse_utc(item["close_time"]) for item in batch)
        assert len(batch) * (((end - start + 59) // 60) + 1) <= 9_000


def test_benchmark_hours_cover_each_settlement_minute():
    rows = [
        market(1, "00:30", "00:45"),
        market(2, "00:45", "01:00"),
        market(3, "01:00", "01:15"),
        market(4, "01:45", "02:00"),
    ]
    assert benchmark_hours(rows) == [1767225600, 1767229200]


def test_registration_is_read_only_and_deterministic():
    registration = Acquisition(1, 2, 3, True).registration()
    assert registration["series"] == "KXBTC15M"
    sources = " ".join(
        endpoint
        for value in registration["sources"].values()
        for endpoint in (value if isinstance(value, list) else [value])
    )
    assert "order" not in sources.lower()
    assert registration == Acquisition(1, 2, 3, True).registration()


def test_archive_client_exposes_no_write_method():
    client = ArchiveClient()
    try:
        assert not hasattr(client, "post")
    finally:
        asyncio.run(client.close())


def test_archive_client_authenticates_only_its_read_request():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    observed = {}

    def handle(request):
        observed.update(request=request)
        return httpx.Response(200, json={})

    client = ArchiveClient("read-test", pem, transport=httpx.MockTransport(handle))
    try:
        asyncio.run(client.get("/markets", {"limit": 1}))
    finally:
        asyncio.run(client.close())

    request = observed["request"]
    assert request.method == "GET"
    assert request.headers["KALSHI-ACCESS-KEY"] == "read-test"
    message = (
        request.headers["KALSHI-ACCESS-TIMESTAMP"] + request.method + request.url.path
    ).encode()
    key.public_key().verify(
        base64.b64decode(request.headers["KALSHI-ACCESS-SIGNATURE"]),
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
        hashes.SHA256(),
    )

