from market_shrunk_price_band_holdout.registration import registration, registration_hash


def test_study_026_freezes_one_candidate_and_no_order_authority():
    study = registration()
    assert study["study"] == "026"
    assert study["candidate"]["excluded_selected_ask"] == ["0.65", "0.70"]
    assert study["candidate"]["first_base_signal_consumes_market"] is True
    assert study["execution_guard"]["explicit_unlock_flag_required"] is True
    assert study["execution_guard"]["no_parameter_search"] is True
    assert study["interpretation"]["production_orders_authorized"] is False
    assert len(registration_hash()) == 64
