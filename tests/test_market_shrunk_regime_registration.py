from market_shrunk_regime_analysis.registration import (
    FEATURES,
    MINIMUM_PARTITION_BUCKET_TRADES,
    registration,
    registration_hash,
)


def test_study_025_is_diagnostic_and_keeps_holdout_locked():
    study = registration()
    assert study["study"] == "025"
    assert study["interpretation"]["diagnostic_only"] is True
    assert study["interpretation"]["no_automatic_filter_selection"] is True
    assert study["interpretation"]["holdout_evaluated"] is False
    assert study["interpretation"]["production_orders_authorized"] is False
    assert MINIMUM_PARTITION_BUCKET_TRADES == 20
    assert "chronological_block" in FEATURES
    assert len(registration_hash()) == 64
