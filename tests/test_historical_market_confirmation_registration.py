from historical_market_confirmation.registration import configurations, registration, registration_hash


def test_study_022_grid_is_fixed_and_unique():
    rows = configurations()
    assert len(rows) == 11_664
    assert len({row["name"] for row in rows}) == len(rows)
    assert registration()["grid"]["configuration_count"] == len(rows)
    assert len(registration_hash()) == 64


def test_study_022_keeps_execution_and_holdout_closed():
    study = registration()
    assert study["risk"]["opens_only_after_all_fixed_1_gates"] is True
    assert study["interpretation"]["holdout_evaluated"] is False
    assert study["interpretation"]["production_orders_authorized"] is False
