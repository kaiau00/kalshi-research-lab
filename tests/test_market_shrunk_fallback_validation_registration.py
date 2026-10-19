from historical_market_confirmation.validation_registration import (
    CONFIGURATION,
    registration,
    registration_hash,
)


def test_study_023_freezes_one_lower_frequency_configuration():
    study = registration()
    assert study["configuration"] == CONFIGURATION
    assert study["validation_gate"]["average_trades_per_observed_day_between"] == [4.0, 7.0]
    assert study["interpretation"]["does_not_satisfy_original_ten_trade_goal"] is True
    assert len(registration_hash()) == 64


def test_study_023_keeps_holdout_and_execution_closed():
    study = registration()
    assert study["risk"]["opens_only_after_validation_and_aggregate_fixed_1_gates"] is True
    assert study["interpretation"]["holdout_evaluated"] is False
    assert study["interpretation"]["production_orders_authorized"] is False
