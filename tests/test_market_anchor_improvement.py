from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from market_anchor_improvement.report import (
    PRIMARY,
    _nearest_rank,
    development_report,
    fit,
    predict,
)


def ns(moment):
    return int(moment.timestamp() * 1e9)


def trade(moment, index, *, raw_yes=0.58, market_yes=0.55, result="yes"):
    side = "yes"
    price = Decimal("0.55")
    quantity = 1
    won = result == side
    fee = Decimal("0.0174")
    payout = Decimal(int(won))
    created = moment + timedelta(minutes=index * 15)
    settled = created + timedelta(minutes=16)
    return {
        "ticker": f"T-{created.isoformat()}-{index}",
        "created_ns": ns(created),
        "fill_ns": ns(created) + 500_000_000,
        "settled_ns": ns(settled),
        "settled_day": settled.date().isoformat(),
        "side": side,
        "won": won,
        "result": result,
        "payout": payout,
        "pnl": payout - price * quantity - fee,
        "fees": fee,
        "cost": price * quantity + fee,
        "limit": price,
        "fill_price": price,
        "filled": quantity,
        "forecast": {
            "yes_probability": raw_yes,
            "z": 0.4 + index / 100,
            "sigma_dollars": 20 + index / 10,
            "expected_average": 80_000,
            "observed_settlement_seconds": index % 20,
            "spot": 80_000,
            "seconds_left": 290 - index,
        },
        "market_yes_probability": market_yes,
        "quoted_binary_spread": Decimal("0.01"),
    }


def training_rows():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for day in range(5):
        for index in range(50):
            rows.append(trade(start + timedelta(days=day), index, result="yes" if index % 2 else "no"))
    return rows


def test_probability_pool_returns_market_when_raw_and_market_agree():
    training = training_rows()
    model = fit(training)
    row = trade(datetime(2026, 1, 6, tzinfo=timezone.utc), 1, raw_yes=0.55, market_yes=0.55)
    score = predict(row, model)
    assert score["pooled_yes_probability"] == pytest.approx(0.55)
    assert score["selected_probability_lower_90"] == pytest.approx(0.55)


def test_nearest_rank_percentile_uses_registered_order_statistic():
    assert _nearest_rank(list(range(1, 11)), 0.90) == 9
    assert _nearest_rank([4], 0.90) == 4


def test_walk_forward_requires_five_prior_dates_and_never_promotes():
    rows = training_rows()
    evaluation_day = datetime(2026, 1, 6, tzinfo=timezone.utc)
    rows.extend(trade(evaluation_day, index, result="yes") for index in range(20))
    report = development_report(rows)
    assert report["evaluation_dates"] == ["2026-01-06"]
    assert report["ineligible_training_decisions"] == 250
    assert report["eligible_decisions"] == 20
    assert report["model_path"]["2026-01-06"]["training_rows"] == 250
    assert report["eligible_probability_comparison"]["pooled_model"]["rows"] == 20
    assert (
        report["candidates"][PRIMARY]["filter_audit"]["independent_pass_counts"][
            "all_candidate_filters"
        ]
        >= 0
    )
    assert report["promotion_authorized"] is False
    assert report["candidates"][PRIMARY]["unresolved_exposure"] == 0


def test_day_ahead_fit_excludes_same_day_outcomes():
    rows = training_rows()
    sixth = datetime(2026, 1, 6, tzinfo=timezone.utc)
    rows.extend(trade(sixth, index, result="yes") for index in range(20))
    seventh = datetime(2026, 1, 7, tzinfo=timezone.utc)
    rows.extend(trade(seventh, index, result="no") for index in range(20))
    report = development_report(rows)
    assert report["model_path"]["2026-01-06"]["training_rows"] == 250
    assert report["model_path"]["2026-01-07"]["training_rows"] == 270
