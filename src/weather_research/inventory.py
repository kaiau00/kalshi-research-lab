"""Bounded public Kalshi market inventory for Study 032."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from research_lab.storage import Store

BASE = "https://external-api.kalshi.com/trade-api/v2"
WEATHER_COMPANY = re.compile(r"according to The Weather Company", re.I)
NWS_CLIMATOLOGICAL = re.compile(
    r"as reported by the National Weather Service's Climatological Report \(Daily\)", re.I
)
NWS_DAILY_CLIMATE = re.compile(r"as reported by the National Weather Service's Daily Climate Report", re.I)


def settlement_source(rule: str) -> str | None:
    """Return a known settlement authority only when the rule explicitly names it."""
    if WEATHER_COMPANY.search(rule or ""):
        return "The Weather Company"
    if NWS_CLIMATOLOGICAL.search(rule or ""):
        return "National Weather Service — Climatological Report (Daily)"
    if NWS_DAILY_CLIMATE.search(rule or ""):
        return "National Weather Service — Daily Climate Report"
    return None


def summarize(markets: list[dict]) -> dict:
    finalized = [market for market in markets if market.get("status") == "finalized"]
    dates = {market.get("event_ticker") for market in finalized} - {None}
    source_counts: dict[str, int] = {}
    for market in finalized:
        source = settlement_source(market.get("rules_primary", ""))
        if source:
            source_counts[source] = source_counts.get(source, 0) + 1
    closes = sorted(market["close_time"] for market in finalized if market.get("close_time"))
    return {
        "finalized_contracts": len(finalized),
        "finalized_event_dates": len(dates),
        "settlement_source_counts": dict(sorted(source_counts.items())),
        "settlement_sources": sorted(source_counts),
        "close_range": [closes[0], closes[-1]] if closes else None,
        "missing_settlement_source": sum(
            settlement_source(market.get("rules_primary", "")) is None for market in finalized
        ),
    }


@dataclass(frozen=True)
class Acquisition:
    series: str
    max_pages: int

    def registration(self) -> dict:
        return {"study": "032", "series": self.series, "max_pages": self.max_pages,
                "endpoint": "/historical/markets", "constraints": ["Public read-only GET requests only; no account or order endpoint.", "Raw page responses are stored receipt-ordered and hash chained.", "Contract rules determine the settlement source; no source proxy is inferred."]}


async def download(path: Path, *, series: str, max_pages: int, resume: bool = False, transport=None) -> dict:
    if not series.startswith("KX") or not 1 <= max_pages <= 20:
        raise ValueError("Invalid series or bounded page count")
    if Path(path).exists() and not resume:
        raise FileExistsError("Inventory already exists; use a new immutable path")
    acquisition, store, cursor, markets = Acquisition(series, max_pages), Store(path), None, []
    try:
        previous = list(store.events())
        registrations = [event.payload for event in previous if event.kind == "weather_inventory_registration"]
        if registrations and registrations != [acquisition.registration()]:
            raise ValueError("Existing inventory registration does not match")
        if not registrations:
            store.append("weather_inventory_registration", acquisition.registration())
        for event in previous:
            if event.kind == "weather_market_page":
                markets.extend(event.payload["response"].get("markets", []))
                cursor = event.payload["response"].get("cursor") or None
        start_page = sum(event.kind == "weather_market_page" for event in previous) + 1
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), transport=transport) as client:
            for page in range(start_page, max_pages + 1):
                params = {"series_ticker": series, "limit": 200, **({"cursor": cursor} if cursor else {})}
                for attempt in range(6):
                    response = await client.get(BASE + "/historical/markets", params=params)
                    if response.status_code != 429:
                        response.raise_for_status()
                        break
                    await asyncio.sleep(min(20, 1 + 2**attempt))
                else:
                    raise RuntimeError("Kalshi historical inventory rate limit retries exhausted")
                payload = response.json()
                rows = payload.get("markets", [])
                if not isinstance(rows, list):
                    raise ValueError("Kalshi historical market response has no market list")
                store.append("weather_market_page", {"page": page, "params": params, "response": payload})
                markets.extend(rows)
                cursor = payload.get("cursor") or None
                if not cursor:
                    break
        result = {
            "registration": acquisition.registration(),
            "pages": page,
            "pagination_complete": cursor is None,
            "next_cursor_present": cursor is not None,
            **summarize(markets),
        }
        store.append("weather_inventory_complete", result)
        store.commit()
        return result
    finally:
        store.close()


def run(path: Path, *, series: str, max_pages: int, resume: bool = False) -> dict:
    return asyncio.run(download(path, series=series, max_pages=max_pages, resume=resume))
