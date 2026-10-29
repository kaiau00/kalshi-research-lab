import asyncio

import httpx
import pytest

from research_lab.storage import Store
from weather_research.ncei import DailySummaryRequest, download, validate_nws_reference


def market(value="81.00"):
    return {
        "ticker": "KXHIGHNY-26AUG26-B80.5",
        "status": "finalized",
        "expiration_value": value,
        "rules_primary": (
            "If the highest temperature recorded in Central Park, New York for August 26, 2026 "
            "as reported by the National Weather Service's Climatological Report (Daily), is between "
            "80-81°, then the market resolves to Yes."
        ),
    }


def test_request_is_bounded_to_a_month_and_central_park_station():
    assert DailySummaryRequest("2026-08-01", "2026-08-31").params()["units"] == "standard"
    with pytest.raises(ValueError, match="31"):
        DailySummaryRequest("2026-08-01", "2026-09-01").params()
    with pytest.raises(ValueError, match="Central Park"):
        DailySummaryRequest("2026-08-01", "2026-08-01", station="OTHER").params()


def test_download_archives_public_rows(tmp_path):
    path = tmp_path / "ncei.sqlite3"

    def handler(request):
        return httpx.Response(200, json=[{"DATE": "2026-08-26", "TMAX": "81"}])

    result = asyncio.run(
        download(
            path,
            requests=[DailySummaryRequest("2026-08-26", "2026-08-26")],
            transport=httpx.MockTransport(handler),
        )
    )
    assert result["retrieved_requests"] == 1
    store = Store(path, readonly=True)
    try:
        assert store.verify()["verified_events"] == 3
    finally:
        store.close()


def test_ncei_reference_requires_an_nws_rule_and_exact_final_match():
    rows = [{"DATE": "2026-08-26", "TMAX": "81"}]
    result = validate_nws_reference([market()], rows)
    assert result["compared_dates"] == 1
    assert result["matching_dates"] == 1
    mismatch = validate_nws_reference([market("82.00")], rows)
    assert mismatch["matching_dates"] == 0
    assert mismatch["mismatches"][0]["event_date"] == "2026-08-26"
