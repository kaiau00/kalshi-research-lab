from historical_robust_optimization.registration import (
    RISK_VARIANTS,
    configurations,
    registration,
    registration_hash,
)


def test_study_020_grid_is_fixed_and_unique():
    rows = configurations()
    assert len(rows) == 4_608
    assert len({row["name"] for row in rows}) == len(rows)
    assert registration()["grid"]["configuration_count"] == len(rows)
    assert len(registration_hash()) == 64


def test_study_020_keeps_holdout_locked_and_risk_secondary():
    study = registration()
    assert "remains locked" in study["source"]["holdout"]
    assert study["signal_selection"]["primary_sizing"] == "fixed_1"
    assert study["risk"]["signal_selected_only_with_fixed_1"] is True
    assert set(RISK_VARIANTS) == {
        "fixed_1",
        "fixed_1_50",
        "fixed_2",
        "fixed_3",
        "sixteenth_kelly_cap_3",
        "eighth_kelly_cap_3",
    }
    assert study["interpretation"]["holdout_evaluated"] is False
    assert study["interpretation"]["production_orders_authorized"] is False
