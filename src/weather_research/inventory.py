"""Bounded public Kalshi market inventory for Study 032."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from research_lab.storage import Store

BASE = "https://external-api.kalshi.com/trade-api/v2"
SOURCE = re.compile(r"according to (?P<source>[^.]+?)(?:, then the market resolves|\.)", re.I)


def settlement_source(rule: str) -> str | None:
    match = SOURCE.search(rule or "")
    return match.group("source") if match else None


def summarize(markets: list[dict]) -> dict:
    finalized = [market for market in markets if market.get("status") == "finalized"]
    dates = {market.get("event_ticker") for market in finalized} - {None}
    sources = {settlement_source(market.get("rules_primary", "")) for market in finalized} - {None}
    closes = sorted(market["close_time"] for market in finalized if market.get("close_time"))
    return {"finalized_contracts": len(finalized), "finalized_event_dates": len(dates),
            "settlement_sources": sorted(sources), "close_range": [closes[0], closes[-1]] if closes else None,
            "missing_settlement_source": sum(settlement_source(market.get("rules_primary", "")) is None for market in finalized)}


@dataclass(frozen=True)
class Acquisition:
    series: str
    max_pages: int

    def registration(self) -> dict:
        return {"study": "032", "series": self.series, "max_pages": self.max_pages,
                "endpoint": "/historical/markets", "constraints": ["Public read-only GET requests only; no account or order endpoint.", "Raw page responses are stored receipt-ordered and hash chained.", "Contract rules determine the settlement source; no source proxy is inferred."]}


async def download(path: Path, *, series: str, max_pages: int, transport=None) -> dict:
    if not series.startswith("KX") or not 1 <= max_pages <= 20:
        raise ValueError("Invalid series or bounded page count")
    if Path(path).exists():
        raise FileExistsError("Inventory already exists; use a new immutable path")
    acquisition, store, cursor, markets = Acquisition(series, max_pages), Store(path), None, []
    try:
        store.append("weather_inventory_registration", acquisition.registration())
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), transport=transport) as client:
            for page in range(1, max_pages + 1):
                params = {"series_ticker": series, "limit": 200, **({"cursor": cursor} if cursor else {})}
                response = await client.get(BASE + "/historical/markets", params=params)
                response.raise_for_status()
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


def run(path: Path, *, series: str, max_pages: int) -> dict:
    return asyncio.run(download(path, series=series, max_pages=max_pages))
