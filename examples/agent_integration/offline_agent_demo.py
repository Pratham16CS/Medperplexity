"""An agent loop in miniature, runnable without any LLM or API key.

It mimics what the Med Perplexity backend does for one doctor query:

    plan (which drugs?) -> call the tools -> judge the evidence -> decide

The "planner" here is deterministic (``extract_drug_mentions``); in the real backend an LLM node does this.
The point is the *contract*: every tool result has a status, and the decision logic uses it so that a failed
search can never be turned into a reassuring answer.

Run:  python examples/agent_integration/offline_agent_demo.py
"""
import json

from medperplexity.agent_tools import assess_evidence, dispatch, get_finder


def decide(doctor_query: str, patient_conditions: list) -> dict:
    drugs = get_finder().extract_drug_mentions(doctor_query)          # planner stand-in
    if not drugs:
        return {"status": "info", "message": "No medicine named in the request."}

    evidence = dispatch("search_medical_evidence", {
        "drugs": [d.split()[0] for d in drugs],                        # names only; never patient identifiers
        "condition": patient_conditions[0] if patient_conditions else None,
        "intent": "interaction" if len(drugs) > 1 else "safety",
    })
    savings = dispatch("find_generic_substitute", {"drugs": drugs})

    verdict = assess_evidence(evidence)
    # The guard that matters: only direct evidence may support a clear answer.
    if not verdict["can_support_clear_recommendation"]:
        status, message = "caution", f"Evidence {verdict['level']}: {verdict['reason']} Review guidelines manually."
    else:
        status, message = "info", "Direct evidence found; see cited PMIDs."

    return {
        "status": status, "message": message, "drugs": drugs,
        "cited_pmids": evidence["data"].get("pmids", []),
        "evidence_status": evidence["status"], "evidence_retryable": evidence["retryable"],
        "substitutes": [
            {"input": r["input"], "found": r["found"], "ambiguous": r["ambiguous"],
             "generic": r["match"]["generic_name"] if r["found"] else None,
             "saving_percent": r["match"]["savings_percent"] if r["found"] else None}
            for r in savings["data"].get("results", [])],
    }


if __name__ == "__main__":
    print(json.dumps(decide("Prescribe Telma 40 and Atorlip 10 for Rahul", ["hypertension"]), indent=2))
