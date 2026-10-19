from decimal import Decimal

from historical_market_confirmation.kelly import quantity_for_budget, target_budget
from research_lab.engine import entry_fee
from research_lab.settings import Experiment


def test_kelly_budgets_are_fractional_and_capped():
    cfg = Experiment()
    budgets = []
    for variant in (
        "kelly_1_32_cap_3",
        "kelly_1_16_cap_3",
        "kelly_1_8_cap_3",
        "kelly_1_4_cap_3",
        "kelly_1_2_cap_3",
    ):
        budget, full_kelly = target_budget(
            variant, 0.75, Decimal("0.60"), Decimal("100"), cfg
        )
        assert full_kelly is not None
        assert Decimal(0) <= budget <= Decimal("3.00")
        budgets.append(budget)
    assert budgets == sorted(budgets)


def test_integer_quantity_includes_fee_inside_budget():
    cfg = Experiment()
    budget = Decimal("1.00")
    price = Decimal("0.45")
    quantity = quantity_for_budget(price, budget, Decimal("100"), cfg)
    assert price * quantity + entry_fee(price, quantity, cfg) <= budget
