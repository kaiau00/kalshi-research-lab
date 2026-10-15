from decimal import Decimal

from historical_optimization.study import (
    _budget,
    _quantity,
    blend_probability,
    full_kelly_fraction,
)
from research_lab.engine import entry_fee
from research_lab.settings import Experiment


def test_log_odds_blend_has_fixed_endpoints():
    assert abs(blend_probability(0.7, 0.4, 0) - 0.7) < 1e-12
    assert abs(blend_probability(0.7, 0.4, 1) - 0.4) < 1e-12
    mixed = blend_probability(0.7, 0.4, 0.5)
    assert 0.4 < mixed < 0.7


def test_full_kelly_uses_all_in_contract_cost():
    cost = Decimal("0.40")
    assert full_kelly_fraction(0.40, cost) == 0
    assert full_kelly_fraction(0.55, cost) == Decimal("0.25")


def test_fractional_kelly_uses_current_cash_and_three_dollar_cap():
    cfg = Experiment()
    budget, kelly = _budget("quarter_kelly_cap_3", 0.75, Decimal("0.40"), Decimal("100"), cfg)
    assert kelly is not None and kelly > 0
    assert budget == Decimal("3.00")
    smaller, _ = _budget("quarter_kelly_cap_3", 0.45, Decimal("0.40"), Decimal("10"), cfg)
    assert Decimal(0) < smaller < Decimal("3.00")


def test_integer_quantity_keeps_fee_inside_budget():
    cfg = Experiment()
    quantity = _quantity(Decimal("0.30"), Decimal("1.00"), Decimal("100"), cfg)
    assert quantity == 3
    assert Decimal("0.30") * quantity + entry_fee(Decimal("0.30"), quantity, cfg) <= 1
