from medperplexity.claim_support import assess_claim_support


def evidence():
    return {"status": "ok", "data": {"articles": [
        {"pmid": "12345678", "title": "Example study", "abstract":
         "Telmisartan reduced systolic blood pressure in adults with hypertension."}
    ]}}


def check(**overrides):
    item = {"claim": "Telmisartan reduced systolic blood pressure in adults with hypertension.",
            "pmid": "12345678", "verdict": "supported",
            "evidence_quote": "Telmisartan reduced systolic blood pressure in adults with hypertension.",
            "rationale": "The abstract directly states the outcome."}
    item.update(overrides)
    return item


def test_supported_claim_needs_retrieved_pmid_and_exact_abstract_quote():
    result = assess_claim_support([check()], evidence())
    assert result["status"] == "supported"
    assert result["supported"] == 1
    assert result["checks"][0]["quote_valid"] is True


def test_unrelated_or_invented_pmid_fails_closed():
    result = assess_claim_support([check(pmid="99999999")], evidence())
    assert result["status"] == "insufficient"
    assert result["checks"][0]["passed"] is False


def test_non_verbatim_quote_fails_closed():
    result = assess_claim_support([check(evidence_quote="Telmisartan cures hypertension permanently.")], evidence())
    assert result["status"] == "insufficient"
    assert result["checks"][0]["quote_valid"] is False


def test_partial_or_contradicted_verdict_fails_closed():
    for verdict in ("partially_supported", "contradicted", "not_found", "out_of_scope"):
        assert assess_claim_support([check(verdict=verdict)], evidence())["status"] == "insufficient"


def test_missing_checks_are_not_assessed():
    assert assess_claim_support([], evidence())["status"] == "not_assessed"
