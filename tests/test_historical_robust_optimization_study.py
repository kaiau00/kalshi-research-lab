from decimal import Decimal

from historical_robust_optimization.study import (
    _budget,
    _quantity,
    probability_for_variance_weight,
)
from research_lab.engine import entry_fee
from research_lab.settings import Experiment


def test_variance_weight_recomputes_probability_from_frozen_components():
    fair = {
        "fast_variance": 0.0004,
        "slow_variance": 0.0001,
        "spot": 100.0,
        "covariance_sum": 100.0,
        "expected_average": 100.1,
        "threshold": 100.0,
    }
    low_fast_weight = probability_for_variance_weight(fair, 0.5)
    high_fast_weight = probability_for_variance_weight(fair, 0.9)
    assert 0.5 < high_fast_weight < low_fast_weight < 1


def test_fixed_and_small_kelly_budgets_share_fee_aware_quantity():
    cfg = Experiment()
    fixed, fixed_kelly = _budget("fixed_2", 0.7, Decimal("0.60"), Decimal("100"), cfg)
    assert fixed == Decimal("2.00")
    assert fixed_kelly is None
    fractional, kelly = _budget(
        "sixteenth_kelly_cap_3", 0.7, Decimal("0.60"), Decimal("100"), cfg
    )
    assert kelly is not None and Decimal(0) < fractional <= Decimal("3.00")
    quantity = _quantity(Decimal("0.60"), fixed, Decimal("100"), cfg)
    assert Decimal("0.60") * quantity + entry_fee(Decimal("0.60"), quantity, cfg) <= fixed
