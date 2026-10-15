from __future__ import annotations

import asyncio
import base64
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

from research_lab.market import epoch_ns
from research_lab.research import write_json
from research_lab.storage import Store

BASE = "https://external-api.kalshi.com/trade-api/v2"
SERIES = "KXBTC15M"
MAX_BATCH_CANDLES = 9_000


def _load_signing_key(key_id=None, pem=None, *, required=False):
    key_id = key_id or os.environ.get("KALSHI_API_KEY_ID", "")
    if pem is None:
        encoded = os.environ.get("KALSHI_PRIVATE_KEY_B64", "")
        text = os.environ.get("KALSHI_PRIVATE_KEY_PEM", "")
        pem = text.encode() if text else base64.b64decode(encoded, validate=True) if encoded else None
    if not key_id or pem is None:
        if required:
            raise ValueError("Kalshi credentials are required for official historical BRTI")
        return None
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, (rsa.RSAPrivateKey, ed25519.Ed25519PrivateKey)):
        raise ValueError("Unsupported Kalshi signing key")
    return key_id, key


def _headers(signer, path):
    if signer is None:
        return {}
    key_id, key = signer
    stamp = str(int(time.time() * 1000))
    message = (stamp + "GET" + path).encode()
    signature = (
        key.sign(message)
        if isinstance(key, ed25519.Ed25519PrivateKey)
        else key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
            hashes.SHA256(),
        )
    )
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": stamp,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
    }


def parse_utc(value: str) -> int:
    text = value.strip()
    if len(text) == 10:
        text += "T00:00:00+00:00"
    elif text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.astimezone(timezone.utc).timestamp())


class ArchiveClient:
    """Narrow market-data GET client with optional read-rate authentication."""

    def __init__(self, key_id=None, pem=None, transport=None):
        self.signer = _load_signing_key(key_id, pem)
        self.http = httpx.AsyncClient(
            timeout=httpx.Timeout(60, connect=10), follow_redirects=False, transport=transport
        )

    async def get(self, path: str, params=None):
        single_candles = (
            path.startswith(f"/historical/markets/{SERIES}-")
            or path.startswith(f"/series/{SERIES}/markets/{SERIES}-")
        ) and path.endswith("/candlesticks")
        allowed = path in ("/markets", "/historical/markets", "/markets/candlesticks") or single_candles
        if not allowed or ":" in path:
            raise ValueError("Only public BTC historical-data GET endpoints are allowed")
        for attempt in range(7):
            try:
                signed_path = "/trade-api/v2" + path
                response = await self.http.get(
                    BASE + path, params=params, headers=_headers(self.signer, signed_path)
                )
            except httpx.TransportError:
                await asyncio.sleep(min(15, 0.5 * 2**attempt))
                continue
            if response.status_code == 429 or response.status_code >= 500:
                await asyncio.sleep(min(15, 0.5 * 2**attempt))
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError("Historical-data retries exhausted")

    async def close(self):
        await self.http.aclose()


class BenchmarkClient:
    """Authenticated, GET-only client restricted to official BRTI hourly history."""

    path = "/trade-api/v2/cfbenchmarks/history/values"

    def __init__(self, key_id=None, pem=None, transport=None):
        self.signer = _load_signing_key(key_id, pem, required=True)
        self.http = httpx.AsyncClient(
            timeout=httpx.Timeout(60, connect=10), follow_redirects=False, transport=transport
        )

    def headers(self):
        return _headers(self.signer, self.path)

    async def hour(self, hour_start: int):
        if hour_start % 3600:
            raise ValueError("BRTI history timestamp must start on a UTC hour")
        timestamp = datetime.fromtimestamp(hour_start, timezone.utc).strftime("%Y-%m-%dT%H:00:00.000Z")
        params = {"id": "BRTI", "timespan": "HOUR", "timestamp": timestamp}
        for attempt in range(7):
            try:
                response = await self.http.get(
                    BASE + "/cfbenchmarks/history/values", params=params, headers=self.headers()
                )
            except httpx.TransportError:
                await asyncio.sleep(min(15, 0.5 * 2**attempt))
                continue
            if response.status_code == 429 or response.status_code >= 500:
                await asyncio.sleep(min(15, 0.5 * 2**attempt))
                continue
            response.raise_for_status()
            return params, response.json()
        raise RuntimeError("Official BRTI history retries exhausted")

    async def close(self):
        await self.http.aclose()


def candle_batches(markets: list[dict]) -> list[list[dict]]:
    """Group adjacent markets below Kalshi's 10,000 requested-candle batch limit."""
    ordered = sorted(markets, key=lambda market: (market["open_time"], market["ticker"]))
    batches: list[list[dict]] = []
    current: list[dict] = []
    for market in ordered:
        candidate = [*current, market]
        start = min(epoch_ns(item["open_time"]) // 10**9 for item in candidate)
        end = max(epoch_ns(item["close_time"]) // 10**9 for item in candidate)
        inclusive_minutes = math.ceil((end - start) / 60) + 1
        if current and (len(candidate) > 100 or len(candidate) * inclusive_minutes > MAX_BATCH_CANDLES):
            batches.append(current)
            current = [market]
        else:
            current = candidate
    if current:
        batches.append(current)
    return batches


def benchmark_hours(markets: list[dict]) -> list[int]:
    """Return each UTC hour containing at least one market's final settlement minute."""
    return sorted({((epoch_ns(market["close_time"]) // 10**9 - 1) // 3600) * 3600 for market in markets})


@dataclass(frozen=True)
class Acquisition:
    start_ts: int
    end_ts: int
    max_markets: int
    include_benchmark: bool

    def registration(self):
        return {
            "schema": 2,
            "series": SERIES,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "max_markets": self.max_markets,
            "include_benchmark": self.include_benchmark,
            "sources": {
                "markets": ["/markets", "/historical/markets"],
                "quotes": "/markets/candlesticks",
                "benchmark": "/cfbenchmarks/history/values?id=BRTI&timespan=HOUR",
            },
            "constraints": [
                "Public read-only GET requests; no account or order endpoint.",
                "End timestamp is exclusive.",
                "Raw API responses are stored in receipt order and hash chained.",
                "One-minute quote candles do not contain depth, queue position or intraminute path.",
                "Authenticated CF Benchmarks passthrough supplies official BRTI seconds by UTC hour.",
                "Raw BRTI may publish at 200 ms; settlement reconstruction uses top-of-second ticks only.",
            ],
        }


def _resume_state(store: Store, registration: dict):
    observed_registration = None
    markets: dict[str, dict] = {}
    quoted: set[str] = set()
    batch_attempted: set[str] = set()
    benchmarks: set[str] = set()
    for event in store.events():
        if event.kind == "archive_registration":
            observed_registration = event.payload
        elif event.kind == "historical_market":
            market = event.payload["market"]
            markets[market["ticker"]] = market
        elif event.kind == "historical_candle_batch":
            batch_attempted.update(event.payload["params"]["market_tickers"].split(","))
            quoted.update(
                item["market_ticker"]
                for item in event.payload["response"].get("markets", [])
                if item.get("candlesticks")
            )
        elif event.kind == "historical_candles":
            quoted.add(event.payload["ticker"])
        elif event.kind == "historical_benchmark":
            benchmarks.add(event.payload["hour_start_ts"])
    if observed_registration is not None and observed_registration != registration:
        raise ValueError("Existing archive registration does not match this acquisition")
    return observed_registration, markets, quoted, batch_attempted, benchmarks


async def _single_candles(client: ArchiveClient, market: dict):
    ticker = market["ticker"]
    params = {
        "start_ts": int(epoch_ns(market["open_time"]) / 1e9),
        "end_ts": int(epoch_ns(market["close_time"]) / 1e9),
        "period_interval": 1,
    }
    for endpoint in (
        f"/historical/markets/{ticker}/candlesticks",
        f"/series/{SERIES}/markets/{ticker}/candlesticks",
    ):
        try:
            result = await client.get(endpoint, params)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                continue
            return market, endpoint, params, None, {"ticker": ticker, "http_status": exc.response.status_code}
        if result.get("candlesticks"):
            return market, endpoint, params, result, None
    return market, None, params, None, {"ticker": ticker, "reason": "no_quote_candles"}


async def _list_markets(store: Store, client: ArchiveClient, acquisition: Acquisition):
    found: dict[str, dict] = {}
    for endpoint in ("/markets", "/historical/markets"):
        cursor = None
        for _ in range(240):
            params = {"series_ticker": SERIES, "limit": 200}
            if cursor:
                params["cursor"] = cursor
            result = await client.get(endpoint, params)
            store.append("historical_listing", {"endpoint": endpoint, "params": params, "response": result})
            rows = result.get("markets", [])
            for market in rows:
                if market.get("result") not in ("yes", "no") or not market["ticker"].startswith(SERIES + "-"):
                    continue
                close = epoch_ns(market["close_time"]) // 10**9
                if acquisition.start_ts <= close < acquisition.end_ts:
                    found[market["ticker"]] = market
            store.commit()
            cursor = result.get("cursor")
            if not cursor:
                break
            settled = [epoch_ns(row["close_time"]) // 10**9 for row in rows if row.get("result") in ("yes", "no")]
            if settled and max(settled) < acquisition.start_ts:
                break
        else:
            raise RuntimeError(f"Listing pagination cap reached for {endpoint}")
    if len(found) > acquisition.max_markets:
        raise RuntimeError(f"Found {len(found)} markets, above max_markets={acquisition.max_markets}")
    return sorted(found.values(), key=lambda market: (market["close_time"], market["ticker"]))


async def download(
    path: Path,
    *,
    start_ts: int,
    end_ts: int,
    max_markets: int = 20_000,
    include_benchmark: bool = True,
    resume: bool = False,
    progress=None,
):
    if end_ts <= start_ts or end_ts - start_ts > 366 * 86400:
        raise ValueError("Historical acquisition must cover more than zero and at most 366 days")
    if not 1 <= max_markets <= 40_000:
        raise ValueError("max_markets must be between 1 and 40,000")
    if path.exists() and not resume:
        raise ValueError("Archive exists; pass resume=True or use a new path")

    acquisition = Acquisition(start_ts, end_ts, max_markets, include_benchmark)
    registration = acquisition.registration()
    store, client = Store(path), ArchiveClient()
    benchmark_client = BenchmarkClient() if include_benchmark else None
    errors: list[dict] = []
    try:
        observed, previous_markets, quoted, batch_attempted, benchmarks = _resume_state(store, registration)
        if observed is None:
            store.append("archive_registration", registration)
            store.commit()

        markets = await _list_markets(store, client, acquisition)
        if progress:
            progress("listed", len(markets), len(markets))
        for market in markets:
            if market["ticker"] not in previous_markets:
                store.append("historical_market", {"market": market})
        store.commit()

        pending_quotes = [
            market for market in markets if market["ticker"] not in quoted and market["ticker"] not in batch_attempted
        ]
        batches = candle_batches(pending_quotes)
        for batch_index, batch in enumerate(batches, 1):
            start = min(epoch_ns(item["open_time"]) // 10**9 for item in batch)
            end = max(epoch_ns(item["close_time"]) // 10**9 for item in batch)
            params = {
                "market_tickers": ",".join(item["ticker"] for item in batch),
                "start_ts": start,
                "end_ts": end,
                "period_interval": 1,
            }
            result = await client.get("/markets/candlesticks", params)
            returned = {item["market_ticker"] for item in result.get("markets", []) if item.get("candlesticks")}
            for market in batch:
                if market["ticker"] not in returned:
                    errors.append({"ticker": market["ticker"], "reason": "no_quote_candles"})
            store.append(
                "historical_candle_batch",
                {"endpoint": "/markets/candlesticks", "params": params, "response": result},
            )
            quoted.update(returned)
            store.commit()
            if progress and (batch_index == len(batches) or batch_index % 25 == 0):
                progress("quotes", batch_index, len(batches))

        missing_quotes = [market for market in markets if market["ticker"] not in quoted]
        completed_singles = 0
        single_concurrency = 8
        for offset in range(0, len(missing_quotes), single_concurrency):
            results = await asyncio.gather(
                *(
                    _single_candles(client, market)
                    for market in missing_quotes[offset : offset + single_concurrency]
                )
            )
            for market, endpoint, params, result, error in results:
                if result is not None:
                    store.append(
                        "historical_candles",
                        {"ticker": market["ticker"], "endpoint": endpoint, "params": params, "response": result},
                    )
                    quoted.add(market["ticker"])
                else:
                    errors.append(error)
                completed_singles += 1
            store.commit()
            # Authenticated ordinary reads have a separate 20 request/second
            # account bucket. Keep the steady-state rate below that limit.
            await asyncio.sleep(0.5)
            if progress and (completed_singles == len(missing_quotes) or completed_singles % 100 == 0):
                progress("historical_quotes", completed_singles, len(missing_quotes))

        if include_benchmark:
            assert benchmark_client is not None
            hours = benchmark_hours(markets)
            pending_hours = [hour for hour in hours if hour not in benchmarks]
            benchmark_concurrency = 3
            completed_hours = 0
            for offset in range(0, len(pending_hours), benchmark_concurrency):
                chunk = pending_hours[offset : offset + benchmark_concurrency]
                results = await asyncio.gather(*(benchmark_client.hour(hour) for hour in chunk))
                for hour_start, (params, result) in zip(chunk, results, strict=True):
                    data = result.get("data", {})
                    if data.get("error") or not data.get("payload"):
                        errors.append(
                            {"hour_start_ts": hour_start, "reason": "invalid_benchmark_response"}
                        )
                        continue
                    store.append(
                        "historical_benchmark",
                        {"hour_start_ts": hour_start, "params": params, "response": result},
                    )
                    benchmarks.add(hour_start)
                completed_hours += len(chunk)
                store.commit()
                # Three requests per batch stays below the four-request CF
                # Benchmarks account limit and lets isolated slow responses overlap.
                await asyncio.sleep(0.8)
                if progress and (
                    completed_hours == len(pending_hours) or completed_hours % 300 == 0
                ):
                    progress("benchmark", completed_hours, len(pending_hours))

        selected_tickers = {market["ticker"] for market in markets}
        quote_count = len(selected_tickers & quoted)
        expected_benchmarks = benchmark_hours(markets) if include_benchmark else []
        summary = {
            "schema": 2,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "selected_markets": len(markets),
            "markets_with_quote_candles": quote_count,
            "expected_hourly_benchmark_events": len(expected_benchmarks),
            "downloaded_hourly_benchmark_events": len(set(expected_benchmarks) & benchmarks),
            "errors": errors,
            "prefix": store.prefix(),
            "database_bytes": store.stats()["bytes"],
            "use": "Research data only; minute candles are not executable order-book replay.",
        }
        store.append("archive_complete", summary)
        store.commit()
        summary["prefix"] = store.prefix()
        summary["database_bytes"] = store.stats()["bytes"]
        write_json(path.with_suffix(".download.json"), summary)
        return summary
    finally:
        store.close()
        await client.close()
        if benchmark_client is not None:
            await benchmark_client.close()

