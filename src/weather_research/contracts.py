"""Parse and verify exact daily-temperature binary contract conditions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

GREATER = re.compile(r"\bis greater than (?P<strike>-?\d+(?:\.\d+)?)°", re.I)
LESS = re.compile(r"\bis less than (?P<strike>-?\d+(?:\.\d+)?)°", re.I)
BETWEEN = re.compile(
    r"\bis between (?P<lower>-?\d+(?:\.\d+)?)-(?P<upper>-?\d+(?:\.\d+)?)°", re.I
)


@dataclass(frozen=True)
class TemperatureCondition:
    kind: str
    lower: Decimal | None = None
    upper: Decimal | None = None

    def resolves_yes(self, value: Decimal) -> bool:
        if self.kind == "greater_than":
            assert self.lower is not None
            return value > self.lower
        if self.kind == "less_than":
            assert self.upper is not None
            return value < self.upper
        if self.kind == "between":
            assert self.lower is not None and self.upper is not None
            return self.lower <= value <= self.upper
        raise ValueError(f"Unsupported condition kind: {self.kind}")


def parse_condition(rule: str) -> TemperatureCondition:
    if match := GREATER.search(rule or ""):
        return TemperatureCondition("greater_than", lower=Decimal(match.group("strike")))
    if match := LESS.search(rule or ""):
        return TemperatureCondition("less_than", upper=Decimal(match.group("strike")))
    if match := BETWEEN.search(rule or ""):
        return TemperatureCondition(
            "between", lower=Decimal(match.group("lower")), upper=Decimal(match.group("upper"))
        )
    raise ValueError("Unsupported weather contract condition")


def verify_market_result(market: dict) -> dict:
    """Verify Kalshi's finalized binary result against its final published value."""
    try:
        final_value = Decimal(str(market["expiration_value"]))
    except (KeyError, InvalidOperation) as exc:
        raise ValueError("Market has no valid expiration value") from exc
    result = str(market.get("result", "")).lower()
    if result not in {"yes", "no"}:
        raise ValueError("Market has no final Yes/No result")
    condition = parse_condition(market.get("rules_primary", ""))
    resolved_yes = condition.resolves_yes(final_value)
    return {
        "ticker": market.get("ticker"),
        "condition_kind": condition.kind,
        "expiration_value_fahrenheit": str(final_value),
        "market_result": result,
        "expected_result": "yes" if resolved_yes else "no",
        "matches_published_result": (result == "yes") == resolved_yes,
    }


def audit_markets(markets: list[dict]) -> dict:
    verified: list[dict] = []
    unverifiable: list[dict] = []
    for market in markets:
        if market.get("status") != "finalized":
            continue
        try:
            verified.append(verify_market_result(market))
        except ValueError as exc:
            unverifiable.append({"ticker": market.get("ticker"), "reason": str(exc)})
    failures = [row for row in verified if not row["matches_published_result"]]
    return {
        "finalized_contracts": len(verified) + len(unverifiable),
        "verified_contracts": len(verified) - len(failures),
        "result_mismatches": failures,
        "unverifiable_contracts": unverifiable,
    }
