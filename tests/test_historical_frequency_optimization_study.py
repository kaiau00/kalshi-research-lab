from historical_frequency_optimization.study import _mean_price, probability_for_model
from historical_robust_optimization.study import probability_for_variance_weight


def _fair():
    return {
        "fast_variance": 0.0004,
        "slow_variance": 0.0001,
        "spot": 100.0,
        "covariance_sum": 100.0,
        "expected_average": 100.1,
        "threshold": 100.0,
        "seconds_left": 30,
        "trailing_60_second_log_return": 0.01,
    }


def test_zero_trend_matches_frozen_zero_drift_probability():
    fair = _fair()
    assert probability_for_model(fair, 0.60, 0.0) == probability_for_variance_weight(fair, 0.60)


def test_momentum_and_mean_reversion_move_probability_in_expected_directions():
    fair = _fair()
    mean_reversion = probability_for_model(fair, 0.60, -0.25)
    neutral = probability_for_model(fair, 0.60, 0.0)
    momentum = probability_for_model(fair, 0.60, 0.50)
    assert mean_reversion < neutral < momentum


def test_missing_mean_entry_price_is_not_a_decimal_nan():
    summary = {"entry_diagnostics": {"mean_entry_price": None}}
    assert _mean_price(summary) is None
