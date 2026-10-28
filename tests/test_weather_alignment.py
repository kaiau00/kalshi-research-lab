from weather_research.alignment import SourceObservation, align_final_value, contract_event_date


def market():
    return {
        "ticker": "KXHIGHNY-26AUG26-T87",
        "event_ticker": "KXHIGHNY-26AUG26",
        "expiration_value": "81.00",
        "rules_primary": (
            "If the maximum temperature recorded at New York City (CLINYC) for Aug 26, 2026, "
            "is greater than 87° fahrenheit according to The Weather Company, then the market "
            "resolves to Yes."
        ),
    }


def observation(**overrides):
    return SourceObservation.from_dict(
        {
            "source": "The Weather Company",
            "station": "CLINYC",
            "observed_for_date": "2026-08-26",
            "reported_at": "2026-08-27T11:10:00Z",
            "value_fahrenheit": "81",
            "raw_record_id": "twc-raw-sha256:example",
            **overrides,
        }
    )


def test_contract_event_date_comes_from_rule_not_expiration_time():
    assert contract_event_date(market()) == "2026-08-26"


def test_alignment_requires_matching_source_date_and_final_value():
    result = align_final_value(market(), observation())
    assert result["matches_kalshi_expiration"] is True
    assert result["difference_fahrenheit"] == "0.00"


def test_alignment_blocks_source_or_date_substitution():
    try:
        align_final_value(market(), observation(source="National Weather Service — Daily Climate Report"))
    except ValueError as exc:
        assert "authority" in str(exc)
    else:
        raise AssertionError("wrong authority must be rejected")
    try:
        align_final_value(market(), observation(observed_for_date="2026-08-27"))
    except ValueError as exc:
        assert "date" in str(exc)
    else:
        raise AssertionError("wrong date must be rejected")
