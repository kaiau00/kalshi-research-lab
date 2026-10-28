import asyncio

import httpx
import pytest

from research_lab.storage import Store
from weather_research.candles import download, epoch_seconds, select_markets


def market(ticker, event, source="The Weather Company"):
    return {
        "ticker": ticker,
        "event_ticker": event,
        "status": "finalized",
        "open_time": "2026-08-25T14:00:00Z",
        "close_time": "2026-08-27T05:00:00Z",
        "rules_primary": f"If it is true according to {source}, then the market resolves to Yes.",
    }


def inventory(path, markets):
    store = Store(path)
    try:
        store.append("weather_inventory_registration", {"study": "032"})
        store.append("weather_market_page", {"response": {"markets": markets}})
        store.commit()
    finally:
        store.close()


def test_select_markets_keeps_one_source_and_complete_ladders(tmp_path):
    path = tmp_path / "inventory.sqlite3"
    inventory(
        path,
        [
            market("A", "E1"),
            market("B", "E1"),
            market("C", "E2", "National Weather Service's Daily Climate Report"),
        ],
    )
    selected = select_markets(path, source="The Weather Company", max_event_dates=2, max_contracts=10)
    assert [row["ticker"] for row in selected] == ["B", "A"]
    assert epoch_seconds(selected[0]["open_time"]) == 1787666400


def test_download_archives_raw_candle_response_and_resumes(tmp_path):
    path = tmp_path / "candles.sqlite3"
    rows = [market("A", "E1")]

    def handler(request):
        assert request.url.path.endswith("/A/candlesticks")
        return httpx.Response(200, json={"candlesticks": [{"end_period_ts": 1}]})

    result = asyncio.run(
        download(path, markets=rows, source="The Weather Company", transport=httpx.MockTransport(handler))
    )
    assert result["retrieved_contracts"] == 1
    resumed = asyncio.run(
        download(
            path,
            markets=rows,
            source="The Weather Company",
            resume=True,
            transport=httpx.MockTransport(handler),
        )
    )
    assert resumed["retrieved_contracts"] == 1
    store = Store(path, readonly=True)
    try:
        assert store.verify()["verified_events"] == 3
    finally:
        store.close()


def test_download_rejects_different_resume_registration(tmp_path):
    path = tmp_path / "candles.sqlite3"
    rows = [market("A", "E1")]

    def handler(request):
        return httpx.Response(200, json={"candlesticks": []})

    asyncio.run(download(path, markets=rows, source="The Weather Company", transport=httpx.MockTransport(handler)))
    with pytest.raises(ValueError, match="registration"):
        asyncio.run(
            download(
                path,
                markets=rows,
                source="National Weather Service — Daily Climate Report",
                resume=True,
                transport=httpx.MockTransport(handler),
            )
        )
