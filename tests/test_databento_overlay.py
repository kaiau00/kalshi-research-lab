from datetime import datetime, timezone
from decimal import Decimal

from databento_overlay import report
from databento_overlay.report import MinuteBars, _fixed_one_dollar_trade, evaluate_symbol
from research_lab.engine import entry_fee
from research_lab.settings import Experiment

MINUTE_NS = 60_000_000_000


def test_minute_features_use_only_completed_bars_and_reject_sparse_history():
    rows = [(index * MINUTE_NS, 100.0 + index) for index in range(62)]
    bars = MinuteBars(rows)
    decision_ns = 61 * MINUTE_NS + 30_000_000_000
    before, reason = bars.features(decision_ns, "yes")
    assert reason is None
    assert before["latest_completed_bar_ns"] == 60 * MINUTE_NS
    assert before["signed_return_5"] > 0

    bars_with_future_spike = MinuteBars(rows + [(62 * MINUTE_NS, 1_000_000.0)])
    after, reason = bars_with_future_spike.features(decision_ns, "yes")
    assert reason is None
    assert after == before

    sparse = MinuteBars(rows[::3])
    missing, reason = sparse.features(decision_ns, "yes")
    assert missing is None
    assert reason == "insufficient_60m_coverage"


def test_one_dollar_sizing_never_exceeds_recorded_fill_or_budget():
    row = {
        "day": "2026-09-21",
        "trade": {
            "ticker": "TEST",
            "fill_price": Decimal("0.40"),
            "filled": 10,
            "won": True,
            "created_ns": 1,
            "settled_ns": 2,
        },
    }
    sized = _fixed_one_dollar_trade(row, Experiment())
    assert 0 < sized["quantity"] <= row["trade"]["filled"]
    assert sized["price"] * sized["quantity"] + sized["fee"] <= Decimal("1.00")
    next_quantity = sized["quantity"] + 1
    assert (
        sized["price"] * next_quantity + entry_fee(sized["price"], next_quantity, Experiment())
        > Decimal("1.00")
    )


def test_walk_forward_models_never_train_on_evaluation_day(monkeypatch):
    monkeypatch.setattr(report, "MINIMUM_TRAINING_DATES", 2)
    monkeypatch.setattr(report, "MINIMUM_TRAINING_ROWS", 4)
    start = int(datetime(2026, 9, 21, tzinfo=timezone.utc).timestamp() * 1e9)
    bars = MinuteBars([
        (start + index * MINUTE_NS, 80_000.0 + index + (index % 7))
        for index in range(4 * 24 * 60)
    ])
    trades = []
    for day in range(3):
        for number in range(3):
            created = start + (day * 24 * 60 + 120 + number * 120) * MINUTE_NS + 30_000_000_000
            trades.append({
                "ticker": f"D{day}-{number}",
                "created_ns": created,
                "settled_ns": created + 15 * MINUTE_NS,
                "side": "yes" if number % 2 else "no",
                "fill_price": Decimal("0.40"),
                "filled": 2,
                "won": bool((day + number) % 2),
                "result": "yes" if (day + number) % 2 else "no",
                "forecast": {"yes_probability": 0.60 if number % 2 else 0.40},
            })
    result = evaluate_symbol(trades, bars, "BTC.c.0")
    assert result["coverage"]["evaluation_dates"] == ["2026-09-23"]
    model = result["model_path"]["2026-09-23"]
    assert model["training_dates"] == ["2026-09-21", "2026-09-22"]
    assert model["training_rows"] == 6
