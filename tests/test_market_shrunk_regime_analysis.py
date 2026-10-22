from decimal import Decimal

from market_shrunk_regime_analysis.study import feature_value, summarize


def _trade(**overrides):
    row = {
        "side": "yes",
        "result": "yes",
        "price": Decimal("0.64"),
        "probability": 0.70,
        "raw_yes_probability": 0.72,
        "market_yes_probability": 0.68,
        "seconds_left": 180,
        "edge": 0.045,
        "fast_slow_variance_ratio": 1.2,
        "created_ns": 0,
        "settled_ns": 1,
        "ticker": "TEST",
        "block": 2,
        "partition": "development",
        "quantity": 1,
        "fee": Decimal("0.01"),
        "payout": Decimal("1"),
        "pnl": Decimal("0.35"),
        "stress_1": Decimal("0.34"),
        "stress_2": Decimal("0.33"),
        "won": True,
    }
    row.update(overrides)
    return row


def test_regime_buckets_are_boundary_stable():
    row = _trade()
    assert feature_value(row, "entry_price") == "55-64"
    assert feature_value(row, "seconds_left") == "121-180"
    assert feature_value(row, "absolute_raw_market_gap") == "3-4.99"
    assert feature_value(row, "modeled_net_edge") == "4-7.99"
    assert feature_value(row, "fast_slow_variance_ratio") == "1-1.99"
    assert feature_value(row, "selected_market_probability") == "65-80"
    assert feature_value(row, "chronological_block") == "3"


def test_summary_preserves_stress_and_concentration():
    rows = [
        _trade(ticker="A", settled_ns=1),
        _trade(
            ticker="B",
            result="no",
            won=False,
            payout=Decimal(0),
            pnl=Decimal("-0.65"),
            stress_1=Decimal("-0.66"),
            stress_2=Decimal("-0.67"),
            settled_ns=2,
        ),
    ]
    report = summarize(rows)
    assert report["trades"] == 2
    assert report["wins"] == 1
    assert report["net_pnl"] == "-0.30"
    assert report["two_cent_stressed_pnl"] == "-0.34"
    assert report["maximum_drawdown"] == "0.65"
