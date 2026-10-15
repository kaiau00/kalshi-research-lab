from __future__ import annotations

import hashlib
import json
import zlib
from decimal import Decimal, InvalidOperation

from research_lab.market import epoch_ns
from research_lab.storage import Store


def _as_decimal(value):
    text = str(value).replace(",", "").strip()
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal") from exc
    if not number.is_finite():
        raise ValueError("non-finite number")
    return number


def _quote_decimal(side, field):
    value = side.get(field + "_dollars")
    if value is None:
        value = side.get(field)
    return _as_decimal(value)


def audit(path):
    store = Store(path, readonly=True)
    try:
        digest = "0" * 64
        verified_events = 0
        registrations = []
        markets: dict[str, dict] = {}
        quote_candles: dict[str, list[dict]] = {}
        benchmarks: dict[int, dict[int, str]] = {}
        nonmonotonic_benchmark_hours = 0
        invalid_benchmark_hours = 0
        completed = []
        end_id = store.prefix()["last_event_id"]
        rows = store.conn.execute(
            "SELECT * FROM events WHERE id<=? ORDER BY id", (end_id,)
        )
        for event_id, received_ns, source_ns, kind, blob, event_digest in rows:
            payload_raw = zlib.decompress(blob)
            source_raw = b"null" if source_ns is None else str(source_ns).encode()
            envelope = (
                b"["
                + str(received_ns).encode()
                + b","
                + source_raw
                + b","
                + json.dumps(kind, separators=(",", ":")).encode()
                + b","
                + payload_raw
                + b"]"
            )
            digest = hashlib.sha256(
                bytes.fromhex(digest) + envelope
            ).hexdigest()
            if digest != event_digest:
                raise ValueError(f"Event hash mismatch at {event_id}")
            verified_events += 1
            payload = json.loads(payload_raw)
            if kind == "archive_registration":
                registrations.append(payload)
            elif kind == "historical_market":
                market = payload["market"]
                markets[market["ticker"]] = market
            elif kind == "historical_candle_batch":
                for row in payload["response"].get("markets", []):
                    quote_candles[row["market_ticker"]] = row.get("candlesticks", [])
            elif kind == "historical_candles":
                quote_candles[payload["ticker"]] = payload["response"].get("candlesticks", [])
            elif kind == "historical_benchmark":
                hour = payload["hour_start_ts"]
                data = payload["response"]["data"]
                values = data.get("payload", [])
                timestamps = [int(row["time"]) for row in values]
                if timestamps != sorted(set(timestamps)):
                    nonmonotonic_benchmark_hours += 1
                if (
                    data.get("error")
                    or not values
                    or timestamps[0] < hour * 1000
                    or timestamps[-1] >= (hour + 3600) * 1000
                ):
                    invalid_benchmark_hours += 1
                benchmarks[hour] = {
                    int(row["time"]): row["value"]
                    for row in values
                    if int(row["time"]) % 1000 == 0
                    and ((int(row["time"]) // 1000 - hour) // 60) % 15 == 14
                }
            elif kind == "archive_complete":
                completed.append(payload)

        if len(registrations) != 1:
            raise ValueError("Archive must contain exactly one acquisition registration")
        integrity = {"verified_events": verified_events, "sha256_chain": digest}

        invalid_quote_rows = 0
        nonmonotonic_quote_markets = 0
        for ticker, rows in quote_candles.items():
            timestamps = [int(row["end_period_ts"]) for row in rows]
            if timestamps != sorted(set(timestamps)):
                nonmonotonic_quote_markets += 1
            for row in rows:
                try:
                    bid = row["yes_bid"]
                    ask = row["yes_ask"]
                    for field in ("open_dollars", "low_dollars", "high_dollars", "close_dollars"):
                        base_field = field.removesuffix("_dollars")
                        bid_value = _quote_decimal(bid, base_field)
                        ask_value = _quote_decimal(ask, base_field)
                        if not (0 <= bid_value <= 1 and 0 <= ask_value <= 1):
                            raise ValueError("quote outside binary range")
                    if _quote_decimal(bid, "close") > _quote_decimal(ask, "close"):
                        raise ValueError("crossed closing quote")
                except (KeyError, TypeError, ValueError, ArithmeticError):
                    invalid_quote_rows += 1

        settlement_matches = 0
        settlement_mismatches = []
        settlement_missing = []
        rounding_differences = 0
        material_mismatches = []
        settlement_metadata_unverifiable = []
        result_mismatches = []
        result_rule_unverifiable = []
        for market in markets.values():
            close = epoch_ns(market["close_time"]) // 10**9
            hour_start = ((close - 1) // 3600) * 3600
            data = benchmarks.get(hour_start)
            if data is None:
                settlement_missing.append(market["ticker"])
                continue
            final_minute = [
                _as_decimal(data[timestamp])
                for timestamp in range((close - 60) * 1000, close * 1000, 1000)
                if timestamp in data
            ]
            if len(final_minute) != 60:
                settlement_missing.append(market["ticker"])
                continue
            reconstructed = (sum(final_minute) / 60).quantize(Decimal("0.01"))
            try:
                official = _as_decimal(market.get("expiration_value", "")).quantize(
                    Decimal("0.01")
                )
            except ValueError:
                official = None
                settlement_metadata_unverifiable.append(market["ticker"])
            if official is not None:
                if reconstructed == official:
                    settlement_matches += 1
                else:
                    mismatch = {
                        "ticker": market["ticker"],
                        "official": str(official),
                        "reconstructed": str(reconstructed),
                    }
                    settlement_mismatches.append(mismatch)
                    if abs(reconstructed - official) <= Decimal("0.01"):
                        rounding_differences += 1
                    else:
                        material_mismatches.append(mismatch)
            if market.get("strike_type") != "greater_or_equal" or market.get("floor_strike") is None:
                result_rule_unverifiable.append(market["ticker"])
                continue
            settlement_value = official if official is not None else reconstructed
            expected_result = (
                "yes" if settlement_value >= _as_decimal(market["floor_strike"]) else "no"
            )
            if market["result"] != expected_result:
                result_mismatches.append(
                    {"ticker": market["ticker"], "official": market["result"], "reconstructed": expected_result}
                )

        closes = sorted(epoch_ns(market["close_time"]) // 10**9 for market in markets.values())
        return {
            "schema": 2,
            "integrity": integrity,
            "registration": registrations[0],
            "archive_complete_records": len(completed),
            "unique_markets": len(markets),
            "market_close_range": [closes[0], closes[-1]] if closes else None,
            "markets_with_quote_candles": len(set(markets) & set(quote_candles)),
            "quote_candles": sum(len(rows) for rows in quote_candles.values()),
            "invalid_quote_rows": invalid_quote_rows,
            "nonmonotonic_quote_markets": nonmonotonic_quote_markets,
            "benchmark_hours": len(benchmarks),
            "nonmonotonic_benchmark_hours": nonmonotonic_benchmark_hours,
            "invalid_benchmark_hours": invalid_benchmark_hours,
            "settlement_reconstruction": {
                "matches": settlement_matches,
                "within_one_cent": settlement_matches + rounding_differences,
                "rounding_difference_count": rounding_differences,
                "material_mismatches": material_mismatches,
                "missing": len(settlement_missing),
                "missing_tickers": settlement_missing,
                "mismatches": settlement_mismatches,
                "metadata_unverifiable": settlement_metadata_unverifiable,
                "result_mismatches": result_mismatches,
                "result_rule_unverifiable": result_rule_unverifiable,
            },
            "limitations": [
                "Minute quote candles have no depth, queue position or intraminute path.",
                "Historical observations are research evidence, not proof of an executable fill.",
            ],
        }
    finally:
        store.close()

