from historical_market_confirmation.kelly_registration import (
    RISK_VARIANTS,
    SIGNAL,
    registration,
    registration_hash,
)


def test_study_024_freezes_signal_and_kelly_variants():
    study = registration()
    assert study["signal"] == SIGNAL
    assert set(RISK_VARIANTS) == {
        "fixed_1",
        "kelly_1_32_cap_3",
        "kelly_1_16_cap_3",
        "kelly_1_8_cap_3",
        "kelly_1_4_cap_3",
        "kelly_1_2_cap_3",
    }
    assert study["risk"]["maximum_kelly_all_in_dollars_per_market"] == "3.00"
    assert len(registration_hash()) == 64


def test_study_024_cannot_promote_or_trade():
    study = registration()
    assert study["interpretation"]["cannot_rescue_or_promote_failed_signal"] is True
    assert study["interpretation"]["holdout_evaluated"] is False
    assert study["interpretation"]["production_orders_authorized"] is False
