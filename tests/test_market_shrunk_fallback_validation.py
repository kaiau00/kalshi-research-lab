from historical_market_confirmation.validation import _price_in_range


def test_validation_price_gate_handles_empty_and_bounded_prices():
    assert not _price_in_range({"entry_diagnostics": {"mean_entry_price": None}})
    assert _price_in_range({"entry_diagnostics": {"mean_entry_price": "0.65"}})
    assert not _price_in_range({"entry_diagnostics": {"mean_entry_price": "0.73"}})
