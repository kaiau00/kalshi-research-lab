from decimal import Decimal

from weather_research.contracts import audit_markets, parse_condition, verify_market_result


def market(rule, value, result):
    return {
        "ticker": "KXHIGHNY-EXAMPLE",
        "status": "finalized",
        "rules_primary": rule,
        "expiration_value": value,
        "result": result,
    }


def test_temperature_conditions_respect_strict_and_inclusive_boundaries():
    assert parse_condition("It is greater than 87°").resolves_yes(Decimal("88"))
    assert not parse_condition("It is greater than 87°").resolves_yes(Decimal("87"))
    assert parse_condition("It is less than 80°").resolves_yes(Decimal("79"))
    assert not parse_condition("It is less than 80°").resolves_yes(Decimal("80"))
    between = parse_condition("It is between 80-81°")
    assert between.resolves_yes(Decimal("80"))
    assert between.resolves_yes(Decimal("81"))


def test_verification_compares_final_value_to_published_binary_result():
    yes = market("It is between 80-81°, then the market resolves", "81.00", "yes")
    no = market("It is greater than 87°, then the market resolves", "87.00", "no")
    assert verify_market_result(yes)["matches_published_result"] is True
    assert verify_market_result(no)["matches_published_result"] is True


def test_audit_exposes_rather_than_hides_a_result_mismatch():
    bad = market("It is less than 80°, then the market resolves", "79.00", "no")
    audit = audit_markets([bad])
    assert audit["verified_contracts"] == 0
    assert audit["result_mismatches"][0]["ticker"] == "KXHIGHNY-EXAMPLE"


def test_audit_reports_a_missing_final_value_as_unverifiable():
    incomplete = market("It is less than 80°, then the market resolves", "", "no")
    audit = audit_markets([incomplete])
    assert audit["verified_contracts"] == 0
    assert audit["unverifiable_contracts"][0]["reason"] == "Market has no valid expiration value"
