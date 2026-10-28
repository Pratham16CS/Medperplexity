"""Conservative source-grounding checks for model-generated medical claims.

This module validates provenance and exact quote presence. It does NOT prove semantic
entailment, clinical truth, or patient-specific appropriateness; the verdict is model-assessed.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

_ALLOWED = {"supported", "partially_supported", "unsupported", "contradicted", "not_found", "out_of_scope"}
_NEGATIVE = {"partially_supported", "unsupported", "contradicted", "not_found", "out_of_scope"}


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def assess_claim_support(claim_checks: Any, evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Check that each claim cites a retrieved PMID and an exact abstract quote.

    `supported` means the model judged the claim supported AND the source/quote
    provenance checks passed. It is not an independent clinical entailment proof.
    """
    if not isinstance(claim_checks, list) or not claim_checks:
        return {"status": "not_assessed", "total": 0, "supported": 0, "issues": ["No claim checks supplied."]}

    articles = (evidence or {}).get("data", {}).get("articles", []) or []
    by_pmid = {str(a.get("pmid", "")).strip(): a for a in articles if isinstance(a, dict)}
    details: List[Dict[str, Any]] = []
    issues: List[str] = []
    supported_count = 0
    has_negative = False

    for i, item in enumerate(claim_checks[:20], start=1):
        if not isinstance(item, dict):
            issues.append(f"Claim {i}: malformed check.")
            has_negative = True
            continue
        claim = str(item.get("claim") or "").strip()
        pmid = str(item.get("pmid") or "").strip()
        verdict = str(item.get("verdict") or "not_found").strip().lower()
        quote = str(item.get("evidence_quote") or "").strip()
        article = by_pmid.get(pmid)
        abstract = _norm(article.get("abstract", "")) if article else ""
        quote_ok = bool(quote) and _norm(quote) in abstract
        verdict_ok = verdict == "supported"
        passed = bool(claim and article and verdict in _ALLOWED and verdict_ok and quote_ok)
        if passed:
            supported_count += 1
        else:
            has_negative = True
            if not claim:
                reason = "missing claim"
            elif not article:
                reason = "PMID was not among retrieved articles"
            elif verdict not in _ALLOWED or not verdict_ok:
                reason = f"model verdict is {verdict!r}, not supported"
            elif not quote_ok:
                reason = "quoted passage is empty or not found verbatim in the cited abstract"
            else:
                reason = "claim check failed"
            issues.append(f"Claim {i}: {reason}.")
        details.append({"claim": claim[:500], "pmid": pmid, "verdict": verdict,
                        "quote_valid": quote_ok, "passed": passed,
                        "rationale": str(item.get("rationale") or "")[:300]})

    if not details:
        status = "not_assessed"
    elif has_negative:
        status = "insufficient"
    elif supported_count == len(details):
        status = "supported"
    else:
        status = "insufficient"
    return {"status": status, "total": len(details), "supported": supported_count,
            "issues": issues, "checks": details}
