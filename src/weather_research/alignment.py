"""Strict, source-aware alignment between weather records and Kalshi contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from weather_research.inventory import settlement_source

RULE_DATE = re.compile(r"\bfor (?P<date>[A-Z][a-z]+ \d{1,2}, \d{4})\b")


@dataclass(frozen=True)
class SourceObservation:
    """Normalized record from the authority explicitly named by a contract rule."""

    source: str
    station: str
    observed_for_date: str
    reported_at: str
    value_fahrenheit: Decimal
    raw_record_id: str

    @classmethod
    def from_dict(cls, row: dict) -> "SourceObservation":
        required = {
            "source",
            "station",
            "observed_for_date",
            "reported_at",
            "value_fahrenheit",
            "raw_record_id",
        }
        missing = sorted(required - set(row))
        if missing:
            raise ValueError(f"Source observation missing fields: {', '.join(missing)}")
        try:
            value = Decimal(str(row["value_fahrenheit"]))
        except InvalidOperation as exc:
            raise ValueError("Source observation has an invalid Fahrenheit value") from exc
        if not value.is_finite():
            raise ValueError("Source observation Fahrenheit value must be finite")
        try:
            datetime.fromisoformat(str(row["reported_at"]).replace("Z", "+00:00"))
            datetime.strptime(str(row["observed_for_date"]), "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("Source observation timestamps must be ISO-8601 and YYYY-MM-DD") from exc
        return cls(
            source=str(row["source"]),
            station=str(row["station"]),
            observed_for_date=str(row["observed_for_date"]),
            reported_at=str(row["reported_at"]),
            value_fahrenheit=value,
            raw_record_id=str(row["raw_record_id"]),
        )


def contract_event_date(market: dict) -> str:
    """Read the observation date from the rule, never from the expiration timestamp."""
    match = RULE_DATE.search(market.get("rules_primary", ""))
    if not match:
        raise ValueError("Market rule has no parseable weather observation date")
    for pattern in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(match.group("date"), pattern).date().isoformat()
        except ValueError:
            continue
    raise ValueError("Market rule has an invalid weather observation date")


def align_final_value(market: dict, observation: SourceObservation) -> dict:
    """Return a transparent final-value check; it does not create a trading signal."""
    source = settlement_source(market.get("rules_primary", ""))
    if source is None:
        raise ValueError("Contract rule settlement source is unknown")
    if observation.source != source:
        raise ValueError("Source observation authority differs from the contract rule")
    event_date = contract_event_date(market)
    if observation.observed_for_date != event_date:
        raise ValueError("Source observation date differs from the contract rule date")
    try:
        kalshi_value = Decimal(str(market["expiration_value"]))
    except (KeyError, InvalidOperation) as exc:
        raise ValueError("Finalized market has no valid Kalshi expiration value") from exc
    return {
        "ticker": market.get("ticker"),
        "event_ticker": market.get("event_ticker"),
        "source": source,
        "station": observation.station,
        "event_date": event_date,
        "source_reported_at": observation.reported_at,
        "source_raw_record_id": observation.raw_record_id,
        "kalshi_expiration_value_fahrenheit": str(kalshi_value),
        "source_value_fahrenheit": str(observation.value_fahrenheit),
        "difference_fahrenheit": str(observation.value_fahrenheit - kalshi_value),
        "matches_kalshi_expiration": observation.value_fahrenheit == kalshi_value,
    }
