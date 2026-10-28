"""Bounded public Kalshi candle collection for the weather feasibility study."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import httpx

from research_lab.storage import Store
from weather_research.inventory import BASE, settlement_source

STUDY = "032"


def epoch_seconds(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def select_markets(
    inventory_path: Path,
    *,
    source: str,
    max_event_dates: int,
    max_contracts: int,
) -> list[dict]:
    """Select complete, finalized event ladders from a single rule-derived source."""
    if not 1 <= max_event_dates <= 20 or not 1 <= max_contracts <= 200:
        raise ValueError("Selection limits must remain bounded")
    store = Store(inventory_path, readonly=True)
    by_ticker: dict[str, dict] = {}
    try:
        for event in store.events():
            if event.kind != "weather_market_page":
                continue
            for market in event.payload["response"].get("markets", []):
                ticker = market.get("ticker")
                if (
                    ticker
                    and market.get("status") == "finalized"
                    and settlement_source(market.get("rules_primary", "")) == source
                    and market.get("event_ticker")
                    and market.get("open_time")
                    and market.get("close_time")
                ):
                    by_ticker[ticker] = market
    finally:
        store.close()

    events: dict[str, list[dict]] = defaultdict(list)
    for market in by_ticker.values():
        events[market["event_ticker"]].append(market)
    selected_events = sorted(
        events.values(), key=lambda ladder: max(row["close_time"] for row in ladder), reverse=True
    )[:max_event_dates]
    selected = sorted(
        (market for ladder in selected_events for market in ladder),
        key=lambda market: (market["close_time"], market["ticker"]),
        reverse=True,
    )
    if len(selected) > max_contracts:
        raise ValueError("Selected contract count exceeds the immutable collection cap")
    if not selected:
        raise ValueError("No finalized markets match the requested settlement source")
    return selected


def registration(markets: list[dict], source: str) -> dict:
    return {
        "study": STUDY,
        "source": source,
        "endpoint": "/historical/markets/{ticker}/candlesticks",
        "period_interval": 1,
        "market_tickers": [market["ticker"] for market in markets],
        "constraints": [
            "Public read-only GET requests only; no account or order endpoint.",
            "Raw responses are receipt-ordered and hash chained.",
            "Candles provide trade and displayed quote history, not inferred order fills.",
        ],
    }


async def download(
    path: Path,
    *,
    markets: list[dict],
    source: str,
    resume: bool = False,
    transport=None,
) -> dict:
    if path.exists() and not resume:
        raise FileExistsError("Candle archive already exists; use a new immutable path")
    expected = registration(markets, source)
    store = Store(path)
    try:
        previous = list(store.events())
        prior_registration = [event.payload for event in previous if event.kind == "weather_candle_registration"]
        if prior_registration and prior_registration != [expected]:
            raise ValueError("Existing candle archive registration does not match")
        if not prior_registration:
            store.append("weather_candle_registration", expected)
            store.commit()
        completed = {event.payload["ticker"] for event in previous if event.kind == "weather_candle"}
        previous_complete = [event.payload for event in previous if event.kind == "weather_candle_complete"]
        if previous_complete and completed == {market["ticker"] for market in markets}:
            return previous_complete[-1]
        errors: list[dict] = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), transport=transport) as client:
            for market in markets:
                ticker = market["ticker"]
                if ticker in completed:
                    continue
                params = {
                    "start_ts": epoch_seconds(market["open_time"]),
                    "end_ts": epoch_seconds(market["close_time"]),
                    "period_interval": 1,
                }
                for attempt in range(6):
                    response = await client.get(
                        f"{BASE}/historical/markets/{ticker}/candlesticks", params=params
                    )
                    if response.status_code != 429:
                        response.raise_for_status()
                        break
                    await asyncio.sleep(min(20, 1 + 2**attempt))
                else:
                    raise RuntimeError("Kalshi weather candle rate limit retries exhausted")
                payload = response.json()
                candles = payload.get("candlesticks")
                if not isinstance(candles, list):
                    raise ValueError("Kalshi candle response has no candle list")
                store.append(
                    "weather_candle",
                    {"ticker": ticker, "params": params, "response": payload},
                )
                completed.add(ticker)
                if not candles:
                    errors.append({"ticker": ticker, "reason": "no_candles"})
                store.commit()
                await asyncio.sleep(0.25)
        result = {
            "registration": expected,
            "requested_contracts": len(markets),
            "retrieved_contracts": len(completed),
            "empty_candle_contracts": errors,
        }
        store.append("weather_candle_complete", result)
        store.commit()
        return result
    finally:
        store.close()

