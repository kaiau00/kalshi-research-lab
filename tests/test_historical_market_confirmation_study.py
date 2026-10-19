from historical_market_confirmation.study import quote_confirmation_passes


def test_quote_confirmation_uses_selected_side_direction():
    assert quote_confirmation_passes("none", "yes", None, 0.50)
    assert quote_confirmation_passes("nonnegative_selected_side_move", "yes", 0.49, 0.50)
    assert not quote_confirmation_passes("nonnegative_selected_side_move", "no", 0.49, 0.50)
    assert quote_confirmation_passes("one_cent_selected_side_move", "no", 0.51, 0.50)
    assert not quote_confirmation_passes("one_cent_selected_side_move", "yes", 0.495, 0.50)
