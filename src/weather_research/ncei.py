"""Bounded public NCEI daily-summary reference collection for NWS-rule contracts."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

from research_lab.storage import Store
from weather_research.alignment import contract_event_date
from weather_research.inventory import settlement_source

BASE = "https://www.ncei.noaa.gov/access/services/data/v1"
CENTRAL_PARK_STATION = "USW00094728"
NWS_SOURCES = {
    "National Weather Service — Climatological Report (Daily)",
    "National Weather Service — Daily Climate Report",
}
MAX_DAYS_PER_REQUEST = 31


@dataclass(frozen=True)
class DailySummaryRequest:
    start_date: str
    end_date: str
    station: str = CENTRAL_PARK_STATION

    def params(self) -> dict[str, str]:
        start, end = date.fromisoformat(self.start_date), date.fromisoformat(self.end_date)
        if end < start or (end - start).days + 1 > MAX_DAYS_PER_REQUEST:
            raise ValueError(f"NCEI requests must cover one to {MAX_DAYS_PER_REQUEST} dates")
        if self.station != CENTRAL_PARK_STATION:
            raise ValueError("Only the documented Central Park station is admitted to Study 032")
        return {
            "dataset": "daily-summaries",
            "stations": self.station,
            "startDate": self.start_date,
            "endDate": self.end_date,
            "format": "json",
            "units": "standard",
            "includeAttributes": "false",
        }


def registration(requests: list[DailySummaryRequest]) -> dict:
    return {
        "study": "032",
        "source": "NCEI daily-summaries reference (not a TWC substitute)",
        "station": CENTRAL_PARK_STATION,
        "requests": [{**asdict(request), "params": request.params()} for request in requests],
        "constraints": [
            "Public read-only GET requests only; no credential or account endpoint.",
            "NCEI is evaluated only against contracts whose own rules name an NWS climate report.",
            "Each retained event must match Kalshi's final expiration value; no mismatched day is usable.",
            "Daily summaries do not provide historical intraday state and cannot support late-day lock-in replay.",
        ],
    }


async def download(
    path: Path,
    *,
    requests: list[DailySummaryRequest],
    resume: bool = False,
    transport=None,
) -> dict:
    if not requests:
        raise ValueError("At least one NCEI request is required")
    if path.exists() and not resume:
        raise FileExistsError("NCEI archive already exists; use a new immutable path")
    expected = registration(requests)
    store = Store(path)
    try:
        previous = list(store.events())
        observed = [event.payload for event in previous if event.kind == "ncei_registration"]
        if observed and observed != [expected]:
            raise ValueError("Existing NCEI archive registration does not match")
        if not observed:
            store.append("ncei_registration", expected)
            store.commit()
        completed = {event.payload["request_index"] for event in previous if event.kind == "ncei_response"}
        prior_complete = [event.payload for event in previous if event.kind == "ncei_complete"]
        if prior_complete and completed == set(range(len(requests))):
            return prior_complete[-1]
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), transport=transport) as client:
            for index, request in enumerate(requests):
                if index in completed:
                    continue
                params = request.params()
                response = await client.get(BASE, params=params)
                response.raise_for_status()
                rows = response.json()
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    raise ValueError("NCEI response must be a JSON list of rows")
                store.append("ncei_response", {"request_index": index, "params": params, "response": rows})
                completed.add(index)
                store.commit()
                await asyncio.sleep(0.25)
        result = {"registration": expected, "retrieved_requests": len(completed)}
        store.append("ncei_complete", result)
        store.commit()
        return result
    finally:
        store.close()


def validate_nws_reference(markets: list[dict], rows: list[dict]) -> dict:
    """Compare NCEI TMAX to final values for contracts that explicitly name NWS."""
    expected: dict[str, set[Decimal]] = defaultdict(set)
    for market in markets:
        source = settlement_source(market.get("rules_primary", ""))
        if market.get("status") != "finalized" or source not in NWS_SOURCES or not market.get("expiration_value"):
            continue
        try:
            expected[contract_event_date(market)].add(Decimal(str(market["expiration_value"])))
        except (ValueError, InvalidOperation):
            continue
    observed: dict[str, Decimal] = {}
    for row in rows:
        try:
            observed[str(row["DATE"])] = Decimal(str(row["TMAX"]))
        except (KeyError, InvalidOperation):
            continue
    comparisons = []
    for event_date in sorted(set(expected) & set(observed)):
        values = expected[event_date]
        comparisons.append(
            {
                "event_date": event_date,
                "kalshi_values": [str(value) for value in sorted(values)],
                "ncei_tmax_fahrenheit": str(observed[event_date]),
                "matches": len(values) == 1 and observed[event_date] in values,
            }
        )
    return {
        "eligible_event_dates": len(expected),
        "ncei_dates": len(observed),
        "compared_dates": len(comparisons),
        "matching_dates": sum(row["matches"] for row in comparisons),
        "mismatches": [row for row in comparisons if not row["matches"]],
    }
