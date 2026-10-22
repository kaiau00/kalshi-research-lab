from decimal import Decimal

from historical_market_confirmation.kelly import target_budget
from research_lab.settings import Experiment


def test_kelly_cap_and_multiplier_can_be_expanded_without_changing_base_registration():
    cfg = Experiment()
    budget, full_kelly = target_budget(
        "kelly_1_4_cap_3",
        0.90,
        Decimal("0.50"),
        Decimal("100"),
        cfg,
        kelly_cap=Decimal("6.00"),
        kelly_multiplier=Decimal("0.50"),
    )
    assert full_kelly is not None
    assert budget == Decimal("6.00")


def test_default_study_024_cap_remains_three_dollars():
    budget, _ = target_budget(
        "kelly_1_2_cap_3",
        0.90,
        Decimal("0.50"),
        Decimal("100"),
        Experiment(),
    )
    assert budget == Decimal("3.00")
