from medperplexity.agent_tools import assess_evidence


def make_result(title, abstract, relaxations=None):
    relaxations = relaxations or []
    return {
        "status": "ok",
        "message": "Search completed",
        "data": {
            "article_count": 1,
            "articles": [{"pmid": "12345678", "title": title, "abstract": abstract}],
            "relaxations": relaxations,
            "high_evidence_filter": not bool(relaxations),
        },
    }


def test_unrelated_article_is_not_direct_evidence():
    result = make_result("Vitamin D and bone density", "A study of vitamin D in adults.")
    verdict = assess_evidence(result, drugs=["warfarin"], intent="safety")
    assert verdict["level"] == "indirect"
    assert verdict["can_support_clear_recommendation"] is False


def test_relevant_drug_article_passes_basic_relevance_check():
    result = make_result("Warfarin safety in adults", "This study evaluates warfarin-associated bleeding risk.")
    verdict = assess_evidence(result, drugs=["warfarin"], intent="safety")
    assert verdict["level"] == "direct"
    assert verdict["can_support_clear_recommendation"] is True


def test_interaction_requires_both_named_drugs():
    result = make_result("Warfarin safety", "Warfarin-associated bleeding risk was assessed.")
    verdict = assess_evidence(result, drugs=["warfarin", "ibuprofen"], intent="interaction")
    assert verdict["level"] == "indirect"
    assert verdict["can_support_clear_recommendation"] is False


def test_broadened_search_remains_indirect():
    result = make_result("Warfarin safety", "Warfarin-associated bleeding risk was assessed.", ["condition broadened"])
    verdict = assess_evidence(result, drugs=["warfarin"], intent="safety")
    assert verdict["level"] == "indirect"
    assert verdict["can_support_clear_recommendation"] is False


def test_no_results_never_supports_clear_recommendation():
    result = {"status": "no_results", "message": "No articles found", "data": {"articles": [], "relaxations": []}}
    verdict = assess_evidence(result, drugs=["warfarin"], intent="safety")
    assert verdict["level"] == "none"
    assert verdict["can_support_clear_recommendation"] is False
