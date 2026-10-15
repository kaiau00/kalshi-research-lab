from historical_backtest.registration import STRATEGIES, registration, registration_hash


def test_historical_screen_registration_is_fixed_and_read_only():
    first = registration()
    assert first == registration()
    assert len(registration_hash()) == 64
    assert first["partition"]["holdout_locked"] is True
    assert first["economics"]["depth_or_fill_claim"] is False
    assert "order" not in first["scope"].lower().replace("no demo or production order authority", "")
    assert set(first["strategies"]) == set(STRATEGIES)


def test_historical_screen_requires_stress_and_concentration_gates():
    gate = registration()["advancement_gate"]
    assert gate["positive_without_top_three_winners"] is True
    assert gate["positive_one_and_two_cent_stress"] is True
    assert gate["minimum_validation_settlements"] == 100
