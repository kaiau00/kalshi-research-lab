import asyncio

import httpx
import pytest

from research_lab.storage import Store
from weather_research.twc import HODRequest, download, registration


def request(**overrides):
    values = {
        "station": "CLINYC",
        "geocode": "40.78,-73.97",
        "start_datetime": "2026-08-26T00:00:00Z",
        "end_datetime": "2026-08-27T00:00:00Z",
        "mapping_evidence": "pending documented source mapping",
    }
    values.update(overrides)
    return HODRequest(**values)


def test_request_is_bounded_and_requires_mapping_evidence():
    assert registration([request()])["requests"][0]["params"]["units"] == "e"
    with pytest.raises(ValueError, match="mapping evidence"):
        request(mapping_evidence="").params()
    with pytest.raises(ValueError, match="48"):
        request(end_datetime="2026-08-29T00:00:00Z").params()


def test_download_archives_raw_response_without_api_key(tmp_path):
    path = tmp_path / "twc.sqlite3"

    def handler(http_request):
        assert http_request.url.params["apiKey"] == "secret-never-persisted"
        return httpx.Response(200, json=[{"validTimeUtc": [1], "temperature": [81]}])

    result = asyncio.run(
        download(
            path,
            requests=[request()],
            api_key="secret-never-persisted",
            transport=httpx.MockTransport(handler),
        )
    )
    assert result["retrieved_requests"] == 1
    store = Store(path, readonly=True)
    try:
        events = list(store.events())
        assert "secret-never-persisted" not in str([event.payload for event in events])
        assert store.verify()["verified_events"] == 3
    finally:
        store.close()
