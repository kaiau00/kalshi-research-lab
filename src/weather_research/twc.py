"""Credential-safe, bounded raw acquisition from The Weather Company HoD API."""

from __future__ import annotations

import asyncio
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import httpx

from research_lab.storage import Store

BASE = "https://api.weather.com"
ENDPOINT = "/v3/wx/hod/r1/direct"
MAX_RANGE_HOURS = 48


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("Weather Company request timestamps must be explicit UTC ISO-8601 values")
    return parsed


@dataclass(frozen=True)
class HODRequest:
    """A bounded request with evidence for its station-to-query mapping."""

    station: str
    geocode: str
    start_datetime: str
    end_datetime: str
    mapping_evidence: str

    def params(self) -> dict[str, str]:
        start, end = _utc(self.start_datetime), _utc(self.end_datetime)
        duration_hours = (end - start).total_seconds() / 3600
        if not 0 < duration_hours <= MAX_RANGE_HOURS:
            raise ValueError(f"Weather Company request must cover 0 to {MAX_RANGE_HOURS} hours")
        if not self.station or not self.geocode or not self.mapping_evidence:
            raise ValueError("Station, geocode and mapping evidence are all required")
        return {
            "geocode": self.geocode,
            "startDateTime": self.start_datetime,
            "endDateTime": self.end_datetime,
            "format": "json",
            "units": "e",
        }


def api_key_from_env() -> str:
    key = os.environ.get("TWC_API_KEY", "").strip()
    if not key:
        raise RuntimeError("TWC_API_KEY is required; keep it in local or Railway environment variables only")
    return key


def registration(requests: list[HODRequest]) -> dict:
    return {
        "study": "032",
        "source": "The Weather Company",
        "endpoint": ENDPOINT,
        "requests": [{**asdict(request), "params": request.params()} for request in requests],
        "constraints": [
            "Raw response acquisition only; this does not create a signal or order.",
            "The API key is excluded from durable records.",
            "Every station-to-geocode mapping needs explicit evidence and final-value verification.",
        ],
    }


async def download(
    path: Path,
    *,
    requests: list[HODRequest],
    api_key: str | None = None,
    resume: bool = False,
    transport=None,
) -> dict:
    if not requests:
        raise ValueError("At least one bounded Weather Company request is required")
    if path.exists() and not resume:
        raise FileExistsError("Weather Company archive already exists; use a new immutable path")
    expected = registration(requests)
    key = api_key or api_key_from_env()
    store = Store(path)
    try:
        previous = list(store.events())
        observed = [event.payload for event in previous if event.kind == "twc_hod_registration"]
        if observed and observed != [expected]:
            raise ValueError("Existing Weather Company archive registration does not match")
        if not observed:
            store.append("twc_hod_registration", expected)
            store.commit()
        completed = {event.payload["request_index"] for event in previous if event.kind == "twc_hod_response"}
        prior_complete = [event.payload for event in previous if event.kind == "twc_hod_complete"]
        if prior_complete and completed == set(range(len(requests))):
            return prior_complete[-1]
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), transport=transport) as client:
            for index, request in enumerate(requests):
                if index in completed:
                    continue
                public_params = request.params()
                response = await client.get(BASE + ENDPOINT, params={**public_params, "apiKey": key})
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    raise ValueError("Weather Company HoD response must be a JSON array")
                store.append(
                    "twc_hod_response",
                    {
                        "request_index": index,
                        "station": request.station,
                        "mapping_evidence": request.mapping_evidence,
                        "params": public_params,
                        "response": payload,
                    },
                )
                completed.add(index)
                store.commit()
                await asyncio.sleep(0.6)
        result = {"registration": expected, "retrieved_requests": len(completed)}
        store.append("twc_hod_complete", result)
        store.commit()
        return result
    finally:
        store.close()
