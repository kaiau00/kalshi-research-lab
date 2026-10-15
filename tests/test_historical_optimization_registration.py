from historical_optimization.registration import configurations, registration, registration_hash


def test_study_019_grid_is_fixed_and_unique():
    rows = configurations()
    assert len(rows) == 1_620
    assert len({row["name"] for row in rows}) == len(rows)
    assert registration()["grid"]["configuration_count"] == len(rows)
    assert len(registration_hash()) == 64


def test_study_019_keeps_holdout_locked_and_signal_primary():
    study = registration()
    assert study["source"]["holdout"] == "newest 20% from Study 018 remains locked"
    assert study["signal_selection"]["primary_sizing"] == "fixed_1"
    assert study["sizing"]["sizing_cannot_promote_a_signal_that_fails_the_fixed_1_gate"] is True
    assert study["interpretation"]["production_orders_authorized"] is False
    assert study["interpretation"]["minute_candle_depth_or_fill_claim"] is False
