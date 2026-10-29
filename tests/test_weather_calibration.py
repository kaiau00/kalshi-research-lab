from decimal import Decimal

from weather_research.calibration import adverse_price, calibration_report, quotes_at_fixed_horizons, taker_fee


def test_fee_and_stress_are_conservative():
    assert taker_fee(Decimal("0.50")) == Decimal("0.017500")
    assert adverse_price(Decimal("0.98")) == Decimal("0.99")
    assert adverse_price(Decimal("0.99")) is None


def test_fixed_horizon_quotes_use_only_prior_quote_and_both_sides():
    markets = {"M": {"event_date": "2026-01-01", "close_second": 1800, "result": "yes"}}
    rows = {"M": [{"end_period_ts": 1500, "yes_ask": {"close": "0.60"}, "yes_bid": {"close": "0.58"}}]}
    quotes = quotes_at_fixed_horizons(markets, rows)
    assert {(quote.horizon_seconds, quote.side, quote.outcome) for quote in quotes} == {
        (300, "yes", True),
        (300, "no", False),
    }


def test_report_keeps_whole_dates_in_chronological_split():
    markets = {}
    rows = {}
    for index in range(5):
        ticker = f"M{index}"
        markets[ticker] = {"event_date": f"2026-01-0{index + 1}", "close_second": 1800, "result": "yes"}
        rows[ticker] = [{"end_period_ts": 1500, "yes_ask": {"close": "0.60"}, "yes_bid": {"close": "0.58"}}]
    report = calibration_report(quotes_at_fixed_horizons(markets, rows))
    assert report["date_split"] == {"development_through": "2026-01-03", "development_dates": 3, "validation_dates": 2}
