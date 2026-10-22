from market_shrunk_expanded_risk.registration import RISK_GRID, registration, registration_hash


def test_study_027_freezes_requested_quarter_and_half_kelly_caps():
    assert set(RISK_GRID) == {
        "quarter_kelly_cap_3",
        "quarter_kelly_cap_4",
        "quarter_kelly_cap_5",
        "quarter_kelly_cap_6",
        "half_kelly_cap_3",
        "half_kelly_cap_4",
        "half_kelly_cap_5",
        "half_kelly_cap_6",
    }
    study = registration()
    assert study["interpretation"]["holdout_evaluated"] is False
    assert study["interpretation"]["production_change_authorized"] is False
    assert len(registration_hash()) == 64
