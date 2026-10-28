from weather_research.inventory import settlement_source, summarize


def market(event="KXHIGHNY-26AUG26", status="finalized", rule=None):
    return {"event_ticker": event, "status": status, "close_time": "2026-08-27T05:00:00Z", "rules_primary": rule or "If max is above 67 according to The Weather Company, then the market resolves to Yes."}


def test_settlement_source_uses_contract_rule():
    assert settlement_source(market()["rules_primary"]) == "The Weather Company"
    assert settlement_source("If it is true according to The Weather Company.") == "The Weather Company"
    assert settlement_source(
        "If the highest temperature is as reported by the National Weather Service's "
        "Climatological Report (Daily), is greater than 92°, then the market resolves to Yes."
    ) == "National Weather Service — Climatological Report (Daily)"
    assert settlement_source(
        "If the highest temperature is as reported by the National Weather Service's "
        "Daily Climate Report, is greater than 92°, then the market resolves to Yes."
    ) == "National Weather Service — Daily Climate Report"
    assert settlement_source("unstructured") is None


def test_summary_counts_finalized_event_dates_and_missing_sources():
    result = summarize([market(), market(), market("KXHIGHNY-26AUG27", rule="unstructured"), market(status="active")])
    assert result["finalized_contracts"] == 3
    assert result["finalized_event_dates"] == 2
    assert result["missing_settlement_source"] == 1
    assert result["settlement_source_counts"] == {"The Weather Company": 2}
