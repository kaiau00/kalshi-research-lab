import pytest

from historical_archive.audit import _as_decimal, _quote_decimal, audit
from historical_archive.downloader import Acquisition
from research_lab.storage import Store


@pytest.mark.parametrize(
    ("strike_fields", "expiration_value", "matches", "metadata_unverifiable", "unverifiable"),
    [
        ({"strike_type": "greater_or_equal", "floor_strike": 99}, "100.00", 1, [], []),
        ({}, "100.00", 1, [], ["KXBTC15M-TEST-00"]),
        (
            {"strike_type": "greater_or_equal", "floor_strike": 99},
            "",
            0,
            ["KXBTC15M-TEST-00"],
            [],
        ),
    ],
)
def test_archive_audit_reconstructs_official_settlement(
    tmp_path, strike_fields, expiration_value, matches, metadata_unverifiable, unverifiable
):
    path = tmp_path / "archive.sqlite3"
    store = Store(path)
    registration = Acquisition(1767225600, 1767229200, 10, True).registration()
    store.append("archive_registration", registration)
    market = {
        "ticker": "KXBTC15M-TEST-00",
        "event_ticker": "KXBTC15M-TEST",
        "open_time": "2026-01-01T00:45:00Z",
        "close_time": "2026-01-01T01:00:00Z",
        "result": "yes",
        "expiration_value": expiration_value,
    } | strike_fields
    store.append("historical_market", {"market": market})
    quote = {
        "end_period_ts": 1767229200,
        "yes_bid": {field: "0.4900" for field in ("open_dollars", "low_dollars", "high_dollars", "close_dollars")},
        "yes_ask": {field: "0.5100" for field in ("open_dollars", "low_dollars", "high_dollars", "close_dollars")},
    }
    store.append(
        "historical_candle_batch",
        {"response": {"markets": [{"market_ticker": market["ticker"], "candlesticks": [quote]}]}},
    )
    second = 1767229140
    timeseries = [{"time": (second + offset) * 1000, "value": "100"} for offset in range(60)]
    store.append(
        "historical_benchmark",
        {
            "hour_start_ts": 1767225600,
            "response": {
                "data": {"serverTime": "2026-01-01T01:01:00Z", "payload": timeseries}
            },
        },
    )
    store.close()

    report = audit(path)
    assert report["integrity"]["verified_events"] == 4
    assert report["markets_with_quote_candles"] == 1
    assert report["invalid_quote_rows"] == 0
    assert report["settlement_reconstruction"] == {
        "matches": matches,
        "within_one_cent": matches,
        "rounding_difference_count": 0,
        "material_mismatches": [],
        "missing": 0,
        "missing_tickers": [],
        "mismatches": [],
        "metadata_unverifiable": metadata_unverifiable,
        "result_mismatches": [],
        "result_rule_unverifiable": unverifiable,
    }


def test_archive_audit_accepts_comma_formatted_official_numbers():
    assert _as_decimal("79,604.96") == _as_decimal("79604.96")


def test_archive_audit_accepts_legacy_and_current_quote_fields():
    assert _quote_decimal({"close": "0.4900"}, "close") == _as_decimal("0.49")
    assert _quote_decimal({"close_dollars": "0.4900"}, "close") == _as_decimal("0.49")

