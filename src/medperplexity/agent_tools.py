"""Agent-facing tools: a small, strict, framework-agnostic interface.

Two tools are exposed to an LLM agent:

* ``search_medical_evidence``  - recent PubMed evidence for drugs / a condition / a clinical intent.
* ``find_generic_substitute``  - Jan Aushadhi generic equivalent and price comparison.

Design rules (they exist because an agent, unlike a person, cannot recover from surprises):

1. **Never raise.** Every call returns the same envelope, whatever the input or failure.
2. **Say what the result means.** ``status`` is one of ``ok`` / ``no_results`` / ``invalid_input`` /
   ``error``; ``answered`` tells the agent whether the lookup actually ran. "Nothing found" and
   "could not search" are never confused; only the first is a (weak) statement about the world.
3. **Bounded output.** Results and abstracts are capped so they fit a prompt.
4. **Honest about looseness.** If a search had to be broadened, ``relaxations`` says how.
5. **Safe inputs.** Terms are sanitised before they reach PubMed; patient identifiers are never needed.
6. **Self-describing.** ``get_tool_specs()`` returns JSON-Schema tool definitions for any LLM API, and
   ``dispatch()`` executes a tool call given only its name and arguments.

Envelope::

    {"tool": str, "status": str, "answered": bool, "retryable": bool, "message": str,
     "data": {...}, "meta": {"retrieved_at", "elapsed_ms", "cached", "warnings", "version"}}
"""

from __future__ import annotations

import concurrent.futures
import functools
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Sequence, Tuple

from . import __version__, pubmed
from .config import DEFAULT_DB_PATH
from .generic_finder import GenericFinder

log = logging.getLogger(__name__)

DISCLAIMER = "Decision support only. A clinician or pharmacist must verify before any prescribing decision."
STATUSES = ("ok", "no_results", "invalid_input", "error")

MAX_DRUGS = 8
MAX_RESULTS_CAP = 10
MAX_TEXT_LEN = 200
DEFAULT_TIMEOUT_S = float(os.environ.get("MEDPERPLEXITY_TIMEOUT_S", "25"))
EVIDENCE_CACHE_TTL_S = float(os.environ.get("MEDPERPLEXITY_CACHE_TTL_S", "3600"))
AMBIGUITY_MARGIN = 2.0  # top matches this close, for different products, are reported as ambiguous


# --------------------------------------------------------------------------- #
# Envelope, caching, timeouts
# --------------------------------------------------------------------------- #
def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _envelope(
    tool: str,
    status: str,
    message: str,
    data: Optional[Dict[str, Any]] = None,
    *,
    retryable: bool = False,
    started: Optional[float] = None,
    cached: bool = False,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    assert status in STATUSES
    return {
        "tool": tool,
        "status": status,
        "answered": status in ("ok", "no_results"),
        "retryable": retryable,
        "message": message,
        "data": data if data is not None else {},
        "meta": {
            "retrieved_at": _now_iso(),
            "elapsed_ms": int((time.perf_counter() - started) * 1000) if started else 0,
            "cached": cached,
            "warnings": list(warnings or []),
            "version": __version__,
        },
    }


class _TTLCache:
    """Tiny thread-safe cache so repeated calls within a session are instant and cheap."""

    def __init__(self, ttl_s: float, max_items: int = 256):
        self.ttl_s, self.max_items = ttl_s, max_items
        self._items: Dict[Any, Tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: Any) -> Any:
        with self._lock:
            hit = self._items.get(key)
            if hit and time.monotonic() - hit[0] < self.ttl_s:
                return hit[1]
            self._items.pop(key, None)
            return None

    def set(self, key: Any, value: Any) -> None:
        if self.ttl_s <= 0:
            return
        with self._lock:
            if len(self._items) >= self.max_items:
                self._items.pop(min(self._items, key=lambda k: self._items[k][0]))
            self._items[key] = (time.monotonic(), value)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


_evidence_cache = _TTLCache(EVIDENCE_CACHE_TTL_S)
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="medperplexity")


class ToolTimeout(Exception):
    """The lookup exceeded its time budget."""


def _run_with_timeout(func: Callable[[], Any], timeout_s: float) -> Any:
    future = _executor.submit(func)
    try:
        return future.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        if future.done():  # the TimeoutError was raised *inside* func (e.g. a socket), not by us
            raise
        future.cancel()
        raise ToolTimeout(f"lookup exceeded {timeout_s:g}s") from None


def clear_cache() -> None:
    _evidence_cache.clear()


def _never_raises(tool: str) -> Callable[[Callable[..., Dict[str, Any]]], Callable[..., Dict[str, Any]]]:
    """Guarantee a tool returns an envelope even if something unforeseen goes wrong anywhere inside it."""

    def decorator(func: Callable[..., Dict[str, Any]]) -> Callable[..., Dict[str, Any]]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            started = time.perf_counter()
            try:
                return func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - this is the contract's last line of defence
                log.exception("%s failed unexpectedly", tool)
                return _envelope(tool, "error", f"Internal error ({type(exc).__name__}).", started=started)

        return wrapper

    return decorator


# --------------------------------------------------------------------------- #
# Input coercion (LLMs send strings where lists are expected, numbers as text, etc.)
# --------------------------------------------------------------------------- #
def _as_text_list(value: Any, max_items: int = MAX_DRUGS) -> Tuple[List[str], List[str]]:
    """Coerce ``value`` to a clean list of short strings. Returns (items, warnings)."""
    warnings: List[str] = []
    if value is None:
        return [], warnings
    if isinstance(value, str):
        value = [part for part in re.split(r"[,;\n]+", value)]
    elif not isinstance(value, (list, tuple, set)):
        return [], [f"ignored value of unsupported type {type(value).__name__}"]
    items: List[str] = []
    for raw in value:
        if not isinstance(raw, str):
            continue
        text = " ".join(raw.split())[:MAX_TEXT_LEN]
        if text and text.lower() not in (i.lower() for i in items):
            items.append(text)
    if len(items) > max_items:
        warnings.append(f"only the first {max_items} items were used")
        items = items[:max_items]
    return items, warnings


def _as_int(value: Any, default: int, low: int, high: int, name: str, warnings: List[str]) -> int:
    try:
        number = int(float(value)) if value is not None else default
    except (TypeError, ValueError):
        warnings.append(f"{name} was not a number; using {default}")
        return default
    clamped = max(low, min(high, number))
    if clamped != number:
        warnings.append(f"{name} adjusted to {clamped} (allowed {low}-{high})")
    return clamped


def _as_optional_text(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())[:MAX_TEXT_LEN]
    return text or None


# --------------------------------------------------------------------------- #
# Tool 1: medical evidence (PubMed)
# --------------------------------------------------------------------------- #
@_never_raises("search_medical_evidence")
def search_medical_evidence(
    drugs: Any = None,
    condition: Any = None,
    intent: str = "safety",
    question: Any = None,
    max_results: Any = pubmed.DEFAULT_RETMAX,
    min_year: Any = pubmed.DEFAULT_MIN_YEAR,
    timeout_s: Optional[float] = None,
) -> Dict[str, Any]:
    """Search PubMed for recent evidence. See ``TOOLS`` for the description shown to the LLM."""
    tool, started = "search_medical_evidence", time.perf_counter()
    try:
        warnings: List[str] = []
        drug_list, w = _as_text_list(drugs)
        warnings += w
        cond = _as_optional_text(condition)
        q = _as_optional_text(question)
        intent = (intent or "safety").strip().lower() if isinstance(intent, str) else "safety"

        if intent not in pubmed.INTENTS:
            return _envelope(tool, "invalid_input",
                             f"intent must be one of: {', '.join(pubmed.INTENTS)}.", started=started)
        if not drug_list and not q:
            return _envelope(tool, "invalid_input",
                             "Provide at least one drug name in 'drugs' (names only, never patient identifiers).",
                             started=started)

        limit = _as_int(max_results, pubmed.DEFAULT_RETMAX, 1, MAX_RESULTS_CAP, "max_results", warnings)
        year = _as_int(min_year, pubmed.DEFAULT_MIN_YEAR, 1900, datetime.now().year, "min_year", warnings)

        key = (tuple(d.lower() for d in drug_list), (cond or "").lower(), intent, (q or "").lower(), limit, year)
        cached = _evidence_cache.get(key)
        if cached is not None:
            out = json.loads(json.dumps(cached))  # fresh copy so callers cannot mutate the cache
            out["meta"]["cached"], out["meta"]["warnings"] = True, warnings + out["meta"]["warnings"]
            out["meta"]["retrieved_at"] = _now_iso()
            return out

        budget = DEFAULT_TIMEOUT_S if timeout_s is None else timeout_s
        found = _run_with_timeout(
            lambda: pubmed.search_evidence(drug_list, cond, intent, q, limit, year), budget
        )
    except ToolTimeout as exc:
        return _envelope(tool, "error", f"Evidence search timed out ({exc}). Evidence is UNAVAILABLE; "
                         "do not answer as if no evidence exists.", retryable=True, started=started)
    except pubmed.PubMedError as exc:
        return _envelope(tool, "error", f"PubMed could not be reached ({exc}). Evidence is UNAVAILABLE; "
                         "do not answer as if no evidence exists.", retryable=True, started=started)
    except ImportError:
        return _envelope(tool, "error", "Biopython is not installed on the server (pip install biopython). "
                         "Evidence is UNAVAILABLE.", started=started)
    except ValueError as exc:
        return _envelope(tool, "invalid_input", str(exc), started=started)
    except Exception as exc:  # last line of defence: an agent must never see a traceback
        log.exception("search_medical_evidence failed")
        return _envelope(tool, "error", f"Internal error ({type(exc).__name__}). Evidence is UNAVAILABLE.",
                         started=started)

    articles = found["articles"]
    if found["relaxations"] and articles:
        warnings.append("Search was broadened: " + "; ".join(found["relaxations"]) +
                        ". Results may only indirectly address the question.")
    counts: Dict[str, int] = {}
    for article in articles:
        counts[article["evidence_type"]] = counts.get(article["evidence_type"], 0) + 1

    data = {
        "drugs": drug_list, "condition": cond, "intent": intent,
        "search_query": found["search_query"],
        "high_evidence_filter": found["high_evidence_filter"],
        "relaxations": found["relaxations"],
        "article_count": found["article_count"],
        "pmids": [a["pmid"] for a in articles],
        "evidence_types": counts,
        "articles": articles,
        "disclaimer": DISCLAIMER,
    }
    if articles:
        result = _envelope(tool, "ok", f"Found {len(articles)} article(s). Cite only the PMIDs returned.",
                           data, started=started, warnings=warnings)
    else:
        result = _envelope(tool, "no_results",
                           "The search ran but PubMed returned no matching articles. This is NOT evidence "
                           "that the drug or combination is safe.", data, started=started, warnings=warnings)
    _evidence_cache.set(key, json.loads(json.dumps(result)))
    return result


# --------------------------------------------------------------------------- #
# Tool 2: generic substitute (Jan Aushadhi)
# --------------------------------------------------------------------------- #
_finder: Optional[GenericFinder] = None
_finder_info: Dict[str, Any] = {}
_finder_lock = threading.Lock()


def set_finder(finder: Optional[GenericFinder], info: Optional[Dict[str, Any]] = None) -> None:
    """Install (or clear) the shared finder; used by tests and by apps that load data themselves."""
    global _finder, _finder_info
    with _finder_lock:
        _finder, _finder_info = finder, info or {}


def get_finder(path: Optional[str | Path] = None) -> GenericFinder:
    """Load the medicine database once and reuse it (raises FileNotFoundError if missing)."""
    global _finder, _finder_info
    with _finder_lock:
        if _finder is None or path is not None:
            db_path = Path(path) if path else DEFAULT_DB_PATH
            finder = GenericFinder.from_json(db_path)
            _finder = finder
            _finder_info = {
                "records": len(finder.records),
                "source_file": db_path.name,
                "modified": datetime.fromtimestamp(db_path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d"),
            }
        return _finder


_MATCH_KEYS = ("generic_name", "unit_size", "matched_on", "matched_text", "match_score",
               "jan_aushadhi_price", "market_average_price", "price_status", "savings_amount", "savings_percent")


def _trim_match(match: Dict[str, Any]) -> Dict[str, Any]:
    trimmed = {k: match.get(k) for k in _MATCH_KEYS}
    trimmed["example_brands"] = list(match.get("example_brands") or [])[:3]
    return trimmed


def _confidence(score: float) -> str:
    return "high" if score >= 95 else "medium" if score >= 90 else "low"


def _lookup_one(finder: GenericFinder, query: str, max_alternatives: int) -> Dict[str, Any]:
    result = finder.search(query, limit=max(max_alternatives, 2))
    if not result["found"]:
        ambiguous = bool(result.get("ambiguous", False))
        clarification = result.get("clarification")

        return {
            "input": query,
            "found": False,
            "ambiguous": ambiguous,
            "confidence": result.get("confidence", "low"),
            "closest": result.get("closest", [])[:max_alternatives],
            "message": result.get("message", "No catalogue match found."),
            "clarification": clarification,
            "action": (
                clarification
                or "No suitable catalogue match was identified. "
                   "Do not infer or invent a substitute."
            ),
        }
    match = result["match"]
    top = match["match_score"]
    others = result["alternatives"]
    lead = _lead_word(match["generic_name"])
    # Real ambiguity = the same single-ingredient drug (or the same combination) in another strength/form
    # scoring about as well, or an exact tie between different products.
    # Combination products that merely share a brand prefix are listed as alternatives, not flagged.
    combo = _is_combination(match["generic_name"])
    competing = [a["generic_name"] for a in others
                 if a["generic_name"] != match["generic_name"] and a["match_score"] >= top - AMBIGUITY_MARGIN
                 and ((_lead_word(a["generic_name"]) == lead and _is_combination(a["generic_name"]) == combo)
                      or a["match_score"] >= top - 0.1)]
    ambiguous = bool(competing)
    return {
        "input": query, "found": True, "ambiguous": ambiguous, "confidence": _confidence(top),
        "ambiguous_with": competing[:3],
        "match": _trim_match(match),
        "alternatives": [_trim_match(a) for a in others[:max_alternatives]],
        "message": result["message"],
        "action": ("Several products match equally well (different strength, dosage form or release type). "
                   "Ask the prescriber which one is meant before recommending a substitute." if ambiguous else
                   "Report the substitute and the saving, and ask the prescriber or pharmacist to verify "
                   "active ingredient, strength and dosage form."),
    }


def _is_combination(generic_name: str) -> bool:
    return bool(re.search(r"\band\b|\+|,", generic_name.lower()))


def _lead_word(generic_name: str) -> str:
    words = re.findall(r"[a-z]+", generic_name.lower())
    return words[0] if words else ""


@_never_raises("find_generic_substitute")
def find_generic_substitute(
    drugs: Any = None,
    strength: Any = None,
    max_alternatives: Any = 2,
) -> Dict[str, Any]:
    """Find Jan Aushadhi generics. See ``TOOLS`` for the description shown to the LLM."""
    tool, started = "find_generic_substitute", time.perf_counter()
    try:
        warnings: List[str] = []
        names, w = _as_text_list(drugs)
        warnings += w
        if not names:
            return _envelope(tool, "invalid_input",
                             "Provide one or more drug names in 'drugs', e.g. ['Atorlip 10'].", started=started)
        alt_count = _as_int(max_alternatives, 2, 0, 5, "max_alternatives", warnings)
        strength_text = _as_optional_text(strength)

        try:
            finder = get_finder()
        except FileNotFoundError:
            return _envelope(tool, "error", "The medicine database is missing. Build it with "
                             "'python -m medperplexity build'.", started=started)

        queries: List[str] = []
        for name in names:
            if len(name.split()) > 4:  # a sentence, not a drug name: pull the drug names out of it
                mentions = finder.extract_drug_mentions(name)
                if mentions:
                    warnings.append(f"Extracted drug names {mentions} from a sentence; pass names only.")
                    queries.extend(m for m in mentions if m.lower() not in (q.lower() for q in queries))
                else:
                    warnings.append("No drug name could be found in the text input.")
            elif name.lower() not in (q.lower() for q in queries):
                queries.append(name)
        queries = queries[:MAX_DRUGS]
        if not queries:
            return _envelope(tool, "invalid_input", "No drug names could be identified in the input.",
                             started=started, warnings=warnings)
        if strength_text and len(queries) == 1:
            queries = [f"{queries[0]} {strength_text}"]
        elif strength_text:
            warnings.append("strength ignored: it applies only when a single drug is given")

        results = [_lookup_one(finder, q, alt_count) for q in queries]
    except Exception as exc:
        log.exception("find_generic_substitute failed")
        return _envelope(tool, "error", f"Internal error ({type(exc).__name__}).", started=started)

    matched = sum(1 for r in results if r["found"])
    data = {"results": results, "database": dict(_finder_info), "disclaimer": DISCLAIMER}
    message = f"{matched} of {len(results)} drug(s) matched a Jan Aushadhi product."
    return _envelope(tool, "ok" if matched else "no_results", message, data, started=started, warnings=warnings)


# --------------------------------------------------------------------------- #
# Registry, specs, dispatch
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ToolDef:
    name: str
    func: Callable[..., Dict[str, Any]]
    description: str
    parameters: Dict[str, Any]  # JSON Schema (object)


_EVIDENCE_DESCRIPTION = (
    "Search PubMed for recent peer-reviewed evidence about one or more drugs: interactions, safety, "
    "contraindications, efficacy, dosing or guidelines. Pass drug NAMES (generic names work best) and an "
    "optional condition. Never pass patient names or identifiers. Returns articles with pmid, title, journal, "
    "date, evidence_type (meta_analysis > systematic_review > guideline > randomized_trial > clinical_trial > "
    "observational > review > case_report > other), abstract and url. Rules for using the result: "
    "(1) status 'no_results' means the search ran and found nothing, which is NOT proof of safety; "
    "(2) status 'error' means the search could not run: say evidence is unavailable and never present your own "
    "recall as evidence; (3) if 'relaxations' is non-empty the search was broadened, so say the evidence is "
    "indirect; (4) cite only PMIDs listed in 'pmids'."
)
_SUBSTITUTE_DESCRIPTION = (
    "Find the Indian government Jan Aushadhi generic equivalent of branded or generic medicines and compare "
    "prices. Pass drug names, optionally with strength (e.g. 'Atorlip 10', 'Metformin 500'), not full "
    "sentences. For each drug returns found, the matched generic with prices and saving, and 'ambiguous'. "
    "If 'ambiguous' is true, ask the prescriber for the strength or dosage form before recommending. "
    "If found is false, say no substitute was found; never invent one. A clinician or pharmacist must "
    "verify any substitution."
)

TOOLS: Dict[str, ToolDef] = {
    "search_medical_evidence": ToolDef(
        "search_medical_evidence", search_medical_evidence, _EVIDENCE_DESCRIPTION,
        {
            "type": "object",
            "properties": {
                "drugs": {"type": "array", "items": {"type": "string"},
                          "description": "Drug names, e.g. ['clopidogrel', 'omeprazole']. Names only."},
                "condition": {"type": "string",
                              "description": "Optional clinical condition, e.g. 'osteoarthritis'."},
                "intent": {"type": "string", "enum": list(pubmed.INTENTS),
                           "description": "What the doctor wants to know. Default 'safety'."},
                "question": {"type": "string",
                             "description": "Optional free-text fallback used only if the structured search finds nothing."},
                "max_results": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS_CAP,
                                "description": "Number of articles (default 5)."},
            },
            "required": ["drugs"],
        },
    ),
    "find_generic_substitute": ToolDef(
        "find_generic_substitute", find_generic_substitute, _SUBSTITUTE_DESCRIPTION,
        {
            "type": "object",
            "properties": {
                "drugs": {"type": "array", "items": {"type": "string"},
                          "description": "Brand or generic names, optionally with strength, e.g. ['Atorlip 10']."},
                "strength": {"type": "string",
                             "description": "Optional strength such as '500mg'; used only when one drug is given."},
            },
            "required": ["drugs"],
        },
    ),
}


def get_tool_specs(style: str = "generic") -> List[Dict[str, Any]]:
    """Tool definitions for an LLM API. ``style``: generic | openai | anthropic."""
    specs = []
    for tool in TOOLS.values():
        schema = json.loads(json.dumps(tool.parameters))
        if style == "openai":
            specs.append({"type": "function",
                          "function": {"name": tool.name, "description": tool.description, "parameters": schema}})
        elif style == "anthropic":
            specs.append({"name": tool.name, "description": tool.description, "input_schema": schema})
        elif style == "generic":
            specs.append({"name": tool.name, "description": tool.description, "parameters": schema})
        else:
            raise ValueError("style must be 'generic', 'openai' or 'anthropic'")
    return specs


def dispatch(name: Any, arguments: Any = None) -> Dict[str, Any]:
    """Run a tool call from an LLM. ``arguments`` may be a dict or a JSON string. Never raises."""
    started = time.perf_counter()
    tool_name = name if isinstance(name, str) else "unknown"
    tool = TOOLS.get(name) if isinstance(name, str) else None
    if tool is None:
        return _envelope(tool_name, "invalid_input",
                         f"Unknown tool. Available tools: {', '.join(TOOLS)}.", started=started)
    if arguments is None or arguments == "":
        arguments = {}
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return _envelope(tool_name, "invalid_input", "Arguments must be a JSON object.", started=started)
    if not isinstance(arguments, dict):
        return _envelope(tool_name, "invalid_input", "Arguments must be a JSON object.", started=started)

    known = set(tool.parameters["properties"])
    extra = sorted(set(arguments) - known)
    result = tool.func(**{k: v for k, v in arguments.items() if k in known})
    if extra:
        result["meta"]["warnings"].append(f"ignored unknown argument(s): {', '.join(extra)}")
    return result


def call_tool_json(name: Any, arguments: Any = None) -> str:
    """``dispatch`` serialised as JSON text, the form most agent frameworks expect as a tool message."""
    return json.dumps(dispatch(name, arguments), ensure_ascii=False)


# --------------------------------------------------------------------------- #
# Helpers for the agent that consumes the tools
# --------------------------------------------------------------------------- #

def _normalised_terms(value: Any) -> set[str]:
    """Return useful alphanumeric terms for a conservative lexical relevance check."""
    if isinstance(value, (list, tuple, set)):
        value = " ".join(str(item) for item in value if item)

    text = str(value or "").lower()
    tokens = re.findall(r"[a-z][a-z0-9]{2,}", text)
    stop_words = {
        "the", "and", "for", "with", "from", "that", "this", "are", "was",
        "were", "use", "using", "used", "about", "after", "before", "does",
        "have", "has", "patient", "clinical", "study", "effect", "effects",
        "review", "safety", "evidence", "treatment", "medicine", "drug",
        "drugs", "risk", "risks", "among", "into", "than", "their", "these",
        "those", "which", "while", "also", "based", "associated", "analysis",
    }
    return {token for token in tokens if token not in stop_words}


def assess_evidence(
    result: Dict[str, Any],
    *,
    question: Optional[str] = None,
    drugs: Optional[Sequence[str]] = None,
    condition: Optional[str] = None,
    intent: Optional[str] = None,
    topic: Optional[str] = None,
) -> Dict[str, Any]:
    """Assess retrieval status and, when query context is supplied, topical relevance.

    This lexical screen is a heuristic only; it is not clinical appraisal and must
    never be treated as proof that a treatment is safe or effective.
    """
    status = result.get("status")
    data = result.get("data") or {}

    if status == "no_results":
        return {
            "level": "none",
            "can_support_clear_recommendation": False,
            "reason": "No articles were found. This is not evidence of safety.",
        }

    if status != "ok":
        return {
            "level": "unavailable",
            "can_support_clear_recommendation": False,
            "reason": result.get("message", "Evidence search did not run."),
        }

    articles = data.get("articles") or []
    relaxations = data.get("relaxations") or []
    high_evidence_filter = data.get("high_evidence_filter", True)
    drug_list = [str(item) for item in (drugs or []) if str(item).strip()]
    drug_terms = [_normalised_terms(item) for item in drug_list]
    condition_terms = _normalised_terms(condition)
    topic_terms = _normalised_terms(topic)
    question_terms = _normalised_terms(question)
    intent_text = str(intent or "").lower()
    has_context = bool(drug_terms or condition_terms or topic_terms or question_terms)

    relevant_articles = []
    if has_context:
        for article in articles:
            article_text = " ".join(
                str(article.get(field) or "")
                for field in ("title", "abstract", "publication_types", "evidence_type")
            )
            article_terms = _normalised_terms(article_text)
            if not article_terms:
                continue

            if drug_terms:
                drug_hits = [bool(terms & article_terms) for terms in drug_terms if terms]
                if not drug_hits:
                    continue
                # Interaction evidence should mention both named medicines.
                drug_match = all(drug_hits) if intent_text == "interaction" and len(drug_hits) > 1 else any(drug_hits)
                if not drug_match:
                    continue

            # For drug-specific questions, require the medicine name(s) to appear.
            # Condition/topic terms are not mandatory because abstracts often use
            # synonyms or omit the indication in indexed metadata. They are used as
            # anchors for topic-only searches below.
            if not drug_terms:
                anchors = condition_terms | topic_terms
                if not anchors:
                    anchors = question_terms
                if anchors and not (anchors & article_terms):
                    continue

            relevant_articles.append(article)

        if not relevant_articles:
            return {
                "level": "indirect",
                "can_support_clear_recommendation": False,
                "reason": (
                    "Articles were retrieved, but none passed the basic lexical "
                    "relevance check for the supplied drug/condition/topic. "
                    "Review the search terms and articles manually."
                ),
            }

    # Broadening always prevents a clear-recommendation evidence label, even if
    # some results overlap lexically with the request.
    if relaxations or high_evidence_filter is False:
        details = "; ".join(str(item) for item in relaxations) or (
            "the high-evidence filter was not retained"
        )
        return {
            "level": "indirect",
            "can_support_clear_recommendation": False,
            "reason": (
                "Articles were found only after retrieval was broadened or filtered "
                "less strictly: " + details + "."
            ),
        }

    count = len(relevant_articles) if has_context else data.get("article_count", len(articles))
    return {
        "level": "direct",
        "can_support_clear_recommendation": True,
        "reason": (
            f"{count} article(s) matched the unbroadened search and basic lexical "
            "relevance check. This is not a clinical conclusion."
            if has_context
            else f"{count} article(s) matched the unbroadened evidence search; "
                 "topical relevance was not independently checked."
        ),
    }


def format_evidence_for_prompt(
    result: Dict[str, Any],
    max_chars: int = 6000,
    *,
    question: Optional[str] = None,
    drugs: Optional[Sequence[str]] = None,
    condition: Optional[str] = None,
    intent: Optional[str] = None,
    topic: Optional[str] = None,
) -> str:
    """Format bounded evidence text with query-aware relevance caveats."""
    verdict = assess_evidence(
        result,
        question=question,
        drugs=drugs,
        condition=condition,
        intent=intent,
        topic=topic,
    )
    header = f"EVIDENCE LEVEL: {verdict['level'].upper()} - {verdict['reason']}"
    if verdict["level"] in ("none", "unavailable"):
        return header

    data = result.get("data") or {}
    lines = [header, f"Search: {data.get('search_query', '')}", ""]
    for article in data.get("articles", []):
        lines.append(
            f"[PMID {article.get('pmid', '')}] {article.get('title', '')} "
            f"({article.get('journal', '')}, {article.get('pub_date', '')}; "
            f"{article.get('evidence_type', 'unknown')})"
        )
        lines.append(f"  Abstract: {article.get('abstract', '')}")
        lines.append(f"  URL: {article.get('url', '')}")
        lines.append("")

    text = "\n".join(lines).rstrip()
    return text if len(text) <= max_chars else text[: max_chars - 40].rstrip() + "\n...[truncated for length]"


def validate_citations(cited_pmids: Sequence[Any], result: Dict[str, Any]) -> Dict[str, List[str]]:
    """Split the PMIDs an LLM cited into those actually returned by the tool and those it invented."""
    allowed = set(result.get("data", {}).get("pmids", []))
    valid: List[str] = []
    invalid: List[str] = []
    for pmid in cited_pmids or []:
        text = str(pmid).strip()
        (valid if text in allowed else invalid).append(text)
    return {"valid": valid, "invalid": invalid}


# --------------------------------------------------------------------------- #
# Optional LangChain / LangGraph adapter
# --------------------------------------------------------------------------- #
# These wrappers live at module level (not inside langchain_tools) so LangChain can resolve their
# type annotations when it builds each tool's argument schema.
IntentName = Literal["interaction", "safety", "contraindication", "efficacy", "dosing", "guideline", "general"]


def _lc_search_medical_evidence(
    drugs: List[str],
    condition: Optional[str] = None,
    intent: IntentName = "safety",
    question: Optional[str] = None,
    max_results: int = pubmed.DEFAULT_RETMAX,
) -> str:
    return call_tool_json("search_medical_evidence", {
        "drugs": drugs, "condition": condition, "intent": intent, "question": question,
        "max_results": max_results})


def _lc_find_generic_substitute(drugs: List[str], strength: Optional[str] = None) -> str:
    return call_tool_json("find_generic_substitute", {"drugs": drugs, "strength": strength})


def langchain_tools() -> List[Any]:
    """The tools as LangChain ``StructuredTool`` objects (works with LangGraph's ``ToolNode``).

    Each tool returns the JSON envelope as text. Requires ``langchain-core``.
    """
    try:
        from langchain_core.tools import StructuredTool
    except ImportError as exc:
        raise ImportError("langchain-core is required: pip install langchain-core") from exc

    return [
        StructuredTool.from_function(func=_lc_search_medical_evidence, name="search_medical_evidence",
                                     description=TOOLS["search_medical_evidence"].description),
        StructuredTool.from_function(func=_lc_find_generic_substitute, name="find_generic_substitute",
                                     description=TOOLS["find_generic_substitute"].description),
    ]
