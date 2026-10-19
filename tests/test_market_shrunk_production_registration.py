from market_shrunk_production.registration import (
    CONFIG_REVISION,
    HOLD_REVISION,
    RISK_REVISION,
    STRATEGY,
    registration,
    registration_hash,
)


def test_market_shrunk_live_registration_is_exact_and_isolated():
    value = registration()
    assert value["strategy"] == STRATEGY == "market_shrunk_half_kelly_001"
    assert value["execution"]["revision"] == CONFIG_REVISION
    assert value["risk"]["revision"] == RISK_REVISION
    assert value["position"]["revision"] == HOLD_REVISION
    assert value["account"]["exchange_index"] == 2
    assert value["account"]["required_initial_cash_dollars"] == "100.0000"
    assert value["risk"]["maximum_all_in_entry_cost"] == "3.00"
    assert value["execution"]["fresh_ledger_starts_paused"] is True
    assert value["position"]["early_exit_submission"] == "disabled"
    assert len(registration_hash()) == 64
