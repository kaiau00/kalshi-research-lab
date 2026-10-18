from historical_frequency_optimization.registration import configurations, registration, registration_hash


def test_study_021_grid_is_fixed_and_unique():
    rows = configurations()
    assert len(rows) == 11_520
    assert len({row["name"] for row in rows}) == len(rows)
    assert registration()["grid"]["configuration_count"] == len(rows)
    assert len(registration_hash()) == 64


def test_study_021_keeps_risk_and_holdout_closed():
    study = registration()
    assert study["development_selection"]["minimum_average_trades_per_observed_day"] == 8.0
    assert study["development_selection"]["maximum_average_trades_per_observed_day"] == 12.0
    assert study["risk"]["opens_only_if_development_validation_and_aggregate_gates_pass"] is True
    assert study["interpretation"]["holdout_evaluated"] is False
    assert study["interpretation"]["production_orders_authorized"] is False
