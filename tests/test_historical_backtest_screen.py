from array import array
from decimal import Decimal

from historical_backtest.screen import (
    Benchmark,
    Market,
    Quote,
    _partition,
    _quantity,
    _quote_close,
    _strategy_filter,
    forecast,
)
from research_lab.settings import Experiment


def benchmark(start, values):
    result = Benchmark(start, start + len(values) - 1)
    result.values = array("d", values)
    result.loaded_seconds = len(values)
    return result


def test_quote_close_accepts_both_archive_schemas():
    assert _quote_close({"close": "0.42"}) == Decimal("0.42")
    assert _quote_close({"close_dollars": "0.4300", "close": "0.42"}) == Decimal("0.4300")


def test_forecast_uses_only_ticks_strictly_before_decision():
    start = 1_000
    prices = [100 + index * 0.001 for index in range(1_000)]
    series = benchmark(start, prices)
    market = Market("KXBTC15M-TEST", 1_900, 100.8, "greater_or_equal", "yes")
    before = forecast(market, 1_840, series, adaptive=True)
    assert before is not None
    series.values[1_840 - start] = 50_000
    series.values[1_850 - start] = 60_000
    assert forecast(market, 1_840, series, adaptive=True) == before


def test_quantity_includes_fee_inside_one_dollar_cap():
    cfg = Experiment()
    assert _quantity(Decimal("0.49"), Decimal("100"), cfg) == 1
    assert _quantity(Decimal("0.30"), Decimal("100"), cfg) == 3


def test_conservative_and_disagreement_gap_boundaries_are_distinct():
    cfg = Experiment()
    quote = Quote(100, Decimal("0.40"), Decimal("0.41"))
    base = {
        "price": Decimal("0.41"),
        "probability": 0.50,
        "edge": 0.08,
        "fair": {"yes_probability": 0.465},
    }
    accepted, _ = _strategy_filter("market_anchor_conservative_001", base, quote, cfg)
    assert accepted
    accepted, reason = _strategy_filter("moderate_disagreement_band_001", base, quote, cfg)
    assert not accepted and reason == "model_market_gap"
    disagreement = {**base, "fair": {"yes_probability": 0.47}}
    accepted, _ = _strategy_filter("moderate_disagreement_band_001", disagreement, quote, cfg)
    assert 0.06 < abs(0.47 - quote.midpoint) <= 0.08
    assert accepted


def test_partition_locks_newest_twenty_percent():
    markets = [
        Market(f"ticker-{index:02d}", index, 100, "greater_or_equal", "yes")
        for index in range(10)
    ]
    parts = _partition(list(reversed(markets)))
    assert [row.close_second for row in parts["development"]] == list(range(6))
    assert [row.close_second for row in parts["validation"]] == [6, 7]
    assert [row.close_second for row in parts["holdout"]] == [8, 9]
