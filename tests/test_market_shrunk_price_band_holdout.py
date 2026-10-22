from decimal import Decimal
from pathlib import Path

import pytest

from market_shrunk_price_band_holdout.study import filter_candidate, run_study


def test_price_band_filter_is_exact_and_consumes_market():
    decisions = [
        {"ticker": "LOW", "price": Decimal("0.6499")},
        {"ticker": "START", "price": Decimal("0.65")},
        {"ticker": "END", "price": Decimal("0.6999")},
        {"ticker": "HIGH", "price": Decimal("0.70")},
    ]
    kept, rejections = filter_candidate(decisions)
    assert [row["ticker"] for row in kept] == ["LOW", "HIGH"]
    assert rejections == {"excluded_65_to_69_cent_first_signal": 2}


def test_holdout_cannot_run_without_explicit_unlock():
    with pytest.raises(ValueError, match="holdout is sealed"):
        run_study(Path("missing.db"), Path("missing-audit.json"))
