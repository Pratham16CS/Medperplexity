"""Real-time PubMed evidence retrieval via NCBI E-utilities (Biopython).

Pipeline for a clinical question such as "Can I prescribe Clopidogrel with Omeprazole?":

1. Strip question filler words so PubMed is not forced to match "can", "I", ...
2. ESearch for high-evidence publications (systematic reviews, guidelines, clinical
   trials, meta-analyses). If nothing is found, broaden to all publication types.
3. EFetch the matching records in a single batched request and parse them into
   clean, JSON-friendly dictionaries.
"""

from __future__ import annotations

import json
import logging
import re
import time
from contextlib import closing
from http.client import HTTPException
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import URLError

from .config import configure_entrez, request_delay

log = logging.getLogger(__name__)

DEFAULT_MIN_YEAR = 2015
DEFAULT_RETMAX = 5

QUALITY_FILTER = (
    "(Systematic Review[pt] OR Guideline[pt] OR Clinical Trial[pt] OR Meta-Analysis[pt])"
)

_TAG_RE = re.compile(r"<[^>]+>")
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-\+/\.']*")

# Words that carry no search value in a natural-language clinical question.
_STOPWORDS = frozenset(
    """
    a an and are as at be been being but by can could did do does for from give had has have
    how i if in into is it its may me might my of on or our prescribe prescribing should
    take than that the their then there these they this to us was we were what when whether
    which why will with would you your
    """.split()
)

_RETRYABLE = (URLError, HTTPException, ConnectionError, TimeoutError, RuntimeError, ValueError)


class PubMedError(Exception):
    """Raised when NCBI cannot be reached or returns unusable data after retries."""


# --------------------------------------------------------------------------- #
# Low-level helpers
# --------------------------------------------------------------------------- #
def _entrez() -> Any:
    """Return a configured ``Bio.Entrez`` module (separate function so tests can mock it)."""
    return configure_entrez()


def _call_with_retry(func: Callable[[], Any], retries: int = 3, backoff: float = 1.0) -> Any:
    """Run ``func`` with exponential backoff, pausing afterwards to respect NCBI rate limits."""
    for attempt in range(retries + 1):
        try:
            result = func()
            time.sleep(request_delay())
            return result
        except _RETRYABLE as exc:
            if attempt == retries:
                raise PubMedError(f"NCBI request failed after {retries + 1} attempts: {exc}") from exc
            wait = backoff * (2**attempt)
            log.warning("NCBI request failed (%s); retrying in %.1fs", exc, wait)
            time.sleep(wait)
    raise PubMedError("unreachable")  # pragma: no cover


def _chunked(items: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def clean_xml_text(text: Any) -> str:
    """Remove leftover HTML/XML tags (<b>, <i>, <sup>...) and collapse whitespace."""
    if not text:
        return ""
    return " ".join(_TAG_RE.sub("", str(text)).split())


def simplify_query(question: str) -> str:
    """Turn a natural-language question into a keyword query PubMed can match.

    >>> simplify_query("Can I prescribe Clopidogrel with Omeprazole?")
    'Clopidogrel Omeprazole'
    """
    tokens = [t.rstrip(".'") for t in _TOKEN_RE.findall(question)]
    kept = [t for t in tokens if t.lower() not in _STOPWORDS]
    return " ".join(kept) if kept else question.strip()


def build_search_term(
    query: str, strict_mode: bool = True, min_year: int = DEFAULT_MIN_YEAR
) -> str:
    """Wrap ``query`` with date, language and (optionally) evidence-quality filters."""
    date_filter = f' AND ("{min_year}/01/01"[Date - Publication] : "3000"[Date - Publication])'
    quality_filter = f" AND {QUALITY_FILTER}" if strict_mode else ""
    language_filter = " AND English[Language]"
    return f"({query}){quality_filter}{date_filter}{language_filter}"


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def get_pub_date(article: Dict[str, Any]) -> str:
    """Publication date (print date first, electronic date as fallback)."""
    try:
        citation = article.get("MedlineCitation", {}).get("Article", {})
        pub_date = citation.get("Journal", {}).get("JournalIssue", {}).get("PubDate", {})

        if "Year" in pub_date:
            parts = [pub_date["Year"], pub_date.get("Month", ""), pub_date.get("Day", "")]
            return " ".join(str(p) for p in parts if p).strip()
        if "MedlineDate" in pub_date:
            return str(pub_date["MedlineDate"])

        article_dates = citation.get("ArticleDate", [])
        if article_dates:
            first = article_dates[0]
            if "Year" in first:
                parts = [first["Year"], first.get("Month", ""), first.get("Day", "")]
                return " ".join(str(p) for p in parts if p).strip() + " (Epub)"
    except (AttributeError, KeyError, IndexError, TypeError):
        pass
    return "Unknown Date"


def extract_abstract_text(article: Dict[str, Any]) -> str:
    """Parse (possibly structured) abstracts, keeping section labels like BACKGROUND/METHODS."""
    try:
        abstract = article.get("MedlineCitation", {}).get("Article", {}).get("Abstract", {})
        sections = abstract.get("AbstractText", [])
        if not sections:
            return "No Abstract Available."
        if isinstance(sections, str):
            sections = [sections]

        parts: List[str] = []
        for section in sections:
            text = clean_xml_text(section)
            label = getattr(section, "attributes", {}).get("Label")
            parts.append(f"{label.upper()}: {text}" if label and text else text)
        return " ".join(p for p in parts if p) or "No Abstract Available."
    except (AttributeError, KeyError, TypeError) as exc:
        return f"Error parsing abstract: {exc}"


def _author_name(author: Dict[str, Any]) -> str:
    if "CollectiveName" in author:
        return str(author["CollectiveName"])
    last = str(author.get("LastName", "")).strip()
    given = str(author.get("Initials") or author.get("ForeName", "")).strip()
    return f"{last} {given}".strip()


def _get_doi(article: Dict[str, Any]) -> str:
    for aid in article.get("PubmedData", {}).get("ArticleIdList", []):
        if getattr(aid, "attributes", {}).get("IdType") == "doi":
            return str(aid)
    for eloc in article.get("MedlineCitation", {}).get("Article", {}).get("ELocationID", []):
        if getattr(eloc, "attributes", {}).get("EIdType") == "doi":
            return str(eloc)
    return ""


def parse_article(article: Dict[str, Any]) -> Dict[str, Any]:
    """Convert one ``PubmedArticle`` record into a plain, JSON-serialisable dict."""
    medline = article.get("MedlineCitation", {})
    info = medline.get("Article", {})
    pmid = str(medline.get("PMID", ""))

    authors: List[str] = []
    affiliations: List[str] = []
    for author in info.get("AuthorList", []):
        name = _author_name(author)
        if name:
            authors.append(name)
        for aff in author.get("AffiliationInfo", []):
            text = str(aff.get("Affiliation", "")).strip()
            if text and text not in affiliations:
                affiliations.append(text)

    journal_info = info.get("Journal", {})
    journal = journal_info.get("ISOAbbreviation") or journal_info.get("Title") or "Unknown Journal"

    mesh_terms = [
        str(h["DescriptorName"]) for h in medline.get("MeshHeadingList", []) if "DescriptorName" in h
    ]
    keywords = [str(k) for group in medline.get("KeywordList", []) for k in group]

    return {
        "pmid": pmid,
        "title": clean_xml_text(info.get("ArticleTitle", "")) or "No Title",
        "journal": str(journal),
        "pub_date": get_pub_date(article),
        "abstract": extract_abstract_text(article),
        "authors": authors,
        "affiliations": affiliations,
        "mesh_terms": mesh_terms,
        "keywords": keywords,
        "doi": _get_doi(article),
        "publication_types": [str(t) for t in info.get("PublicationTypeList", [])],
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
    }


# --------------------------------------------------------------------------- #
# NCBI calls
# --------------------------------------------------------------------------- #
def search_pubmed_ids(
    query: str,
    strict_mode: bool = True,
    retmax: int = DEFAULT_RETMAX,
    min_year: int = DEFAULT_MIN_YEAR,
) -> List[str]:
    """ESearch: return PMIDs (most relevant first) for ``query``."""
    term = build_search_term(query, strict_mode=strict_mode, min_year=min_year)
    entrez = _entrez()

    def _do() -> Any:
        with closing(entrez.esearch(db="pubmed", term=term, retmax=retmax, sort="relevance")) as handle:
            return entrez.read(handle)

    record = _call_with_retry(_do)
    return [str(pmid) for pmid in record.get("IdList", [])]


def fetch_pubmed_articles(id_list: Sequence[str], batch_size: int = 100) -> List[Dict[str, Any]]:
    """EFetch: download raw ``PubmedArticle`` records in batches (one request per batch)."""
    ids = [str(i) for i in id_list]
    if not ids:
        return []
    entrez = _entrez()
    articles: List[Dict[str, Any]] = []
    for chunk in _chunked(ids, batch_size):
        joined = ",".join(chunk)

        def _do(joined: str = joined) -> Any:
            with closing(entrez.efetch(db="pubmed", id=joined, retmode="xml")) as handle:
                return entrez.read(handle)

        data = _call_with_retry(_do)
        articles.extend(data.get("PubmedArticle", []))
    return articles


def fetch_article_details(id_list: Sequence[str]) -> List[Dict[str, Any]]:
    """Fetch and summarise articles (compact form used by the research tool)."""
    summaries = []
    for raw in fetch_pubmed_articles(id_list):
        parsed = parse_article(raw)
        authors = parsed["authors"]
        summaries.append(
            {
                "pmid": parsed["pmid"],
                "title": parsed["title"],
                "journal": parsed["journal"],
                "pub_date": parsed["pub_date"],
                "authors": ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else ""),
                "publication_types": parsed["publication_types"],
                "evidence_type": evidence_type(parsed["publication_types"]),
                "doi": parsed["doi"],
                "abstract": parsed["abstract"],
                "url": parsed["url"],
            }
        )
    return summaries


# --------------------------------------------------------------------------- #
# Public tool
# --------------------------------------------------------------------------- #
def query_pubmed_realtime(question: str, retmax: int = DEFAULT_RETMAX) -> Dict[str, Any]:
    """Answer a clinical question with the best available PubMed evidence.

    Search order: keyword query + high-evidence filter -> keyword query, any evidence
    level -> original wording, any evidence level.
    """
    keywords = simplify_query(question)
    attempts = [(keywords, True, "high_evidence"), (keywords, False, "broad")]
    if keywords != question.strip():
        attempts.append((question.strip(), False, "broad_original_wording"))

    try:
        for query, strict, label in attempts:
            log.info("PubMed search (%s): %s", label, query)
            pmids = search_pubmed_ids(query, strict_mode=strict, retmax=retmax)
            if pmids:
                articles = fetch_article_details(pmids)
                return {
                    "status": "success",
                    "question": question,
                    "search_query": query,
                    "strategy": label,
                    "evidence_count": len(articles),
                    "articles": articles,
                }
    except PubMedError as exc:
        return {"status": "error", "question": question, "message": str(exc)}

    return {"status": "error", "question": question, "message": "No results found."}


def query_pubmed_realtime_json(question: str, retmax: int = DEFAULT_RETMAX) -> str:
    """Same as :func:`query_pubmed_realtime` but returns a JSON string (handy for LLM tool calls)."""
    return json.dumps(query_pubmed_realtime(question, retmax), indent=2, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# Structured clinical search (designed for agents)
# --------------------------------------------------------------------------- #
INTENT_TERMS = {
    "interaction": '(interaction*[Title/Abstract] OR "Drug Interactions"[MeSH Terms])',
    "safety": "(safety[Title/Abstract] OR adverse[Title/Abstract] OR contraindicat*[Title/Abstract])",
    "contraindication": "(contraindicat*[Title/Abstract] OR caution[Title/Abstract] OR avoid*[Title/Abstract])",
    "efficacy": "(efficacy[Title/Abstract] OR effective*[Title/Abstract] OR outcome*[Title/Abstract])",
    "dosing": "(dose[Title/Abstract] OR dosing[Title/Abstract] OR dosage[Title/Abstract])",
    "guideline": "(guideline*[Title/Abstract] OR recommendation*[Title/Abstract])",
    "general": "",
}
INTENTS = tuple(INTENT_TERMS)

# Strongest first. Matched against PubMed publication-type strings.
_EVIDENCE_ORDER = [
    ("meta_analysis", lambda t: t == "meta-analysis"),
    ("systematic_review", lambda t: t == "systematic review"),
    ("guideline", lambda t: t in ("practice guideline", "guideline", "consensus development conference")),
    ("randomized_trial", lambda t: t == "randomized controlled trial"),
    ("clinical_trial", lambda t: t.startswith("clinical trial")),
    ("observational", lambda t: t in ("observational study", "cohort studies", "comparative study", "multicenter study")),
    ("review", lambda t: t == "review"),
    ("case_report", lambda t: t == "case reports"),
]
_MAX_TERM_LEN = 80
_UNSAFE_QUERY_CHARS = re.compile(r'[\[\]\(\)"{}<>\\]')


def evidence_type(publication_types: Sequence[str]) -> str:
    """Strongest evidence category among PubMed publication types ("other" if none match)."""
    lowered = [str(t).strip().lower() for t in publication_types]
    for name, test in _EVIDENCE_ORDER:
        if any(test(t) for t in lowered):
            return name
    return "other"


def sanitize_term(term: Any) -> str:
    """Make a free-text term safe to embed in a PubMed query (no brackets/quotes/operators)."""
    text = _UNSAFE_QUERY_CHARS.sub(" ", str(term or ""))
    text = " ".join(text.split())[:_MAX_TERM_LEN]
    # a bare boolean operator typed by an LLM would change the query's meaning
    return "" if text.upper() in ("AND", "OR", "NOT") else text


def _tiab(term: str) -> str:
    return f'"{term}"[Title/Abstract]' if " " in term else f"{term}[Title/Abstract]"


def build_clinical_query(
    drugs: Sequence[str] = (),
    condition: Optional[str] = None,
    intent: str = "safety",
) -> str:
    """Compose ``drug1 AND drug2 AND condition AND intent-terms`` from structured pieces."""
    clean_drugs = [d for d in (sanitize_term(x) for x in drugs) if d]
    parts = [_tiab(d) for d in clean_drugs]
    cond = sanitize_term(condition)
    if cond:
        parts.append(_tiab(cond))
    intent_clause = INTENT_TERMS.get(intent, INTENT_TERMS["general"])
    if intent_clause:
        parts.append(intent_clause)
    return " AND ".join(parts)


def search_evidence(
    drugs: Sequence[str] = (),
    condition: Optional[str] = None,
    intent: str = "safety",
    question: Optional[str] = None,
    max_results: int = DEFAULT_RETMAX,
    min_year: int = DEFAULT_MIN_YEAR,
    abstract_max_chars: int = 1500,
) -> Dict[str, Any]:
    """Structured PubMed search with progressive, *reported* relaxation.

    Order tried (each only if the previous found nothing):
    strict (high-evidence filter) -> any evidence level -> condition dropped -> intent dropped
    -> keywords from the free-text ``question``. ``relaxations`` lists everything that was loosened,
    so the caller knows how directly the results answer the question.

    Raises :class:`PubMedError` only if NCBI is unreachable; "nothing found" is a normal return.
    """
    clean_drugs = [d for d in (sanitize_term(x) for x in drugs) if d]
    cond = sanitize_term(condition)
    attempts: List[Tuple[str, bool, List[str]]] = []

    def add(query: str, strict: bool, relaxed: List[str]) -> None:
        if query and all(query != a[0] or strict != a[1] for a in attempts):
            attempts.append((query, strict, relaxed))

    if clean_drugs:
        full = build_clinical_query(clean_drugs, cond, intent)
        add(full, True, [])
        add(full, False, ["evidence-quality filter removed"])
        if cond:
            no_cond = build_clinical_query(clean_drugs, None, intent)
            add(no_cond, False, ["evidence-quality filter removed", "condition dropped"])
        if INTENT_TERMS.get(intent):
            bare = build_clinical_query(clean_drugs, None, "general")
            add(bare, False, ["evidence-quality filter removed", "condition dropped", "topic dropped"])
    if question and question.strip():
        add(simplify_query(sanitize_term(question) or question), False,
            ["evidence-quality filter removed", "free-text keywords used"])

    if not attempts:
        raise ValueError("Provide at least one drug name or a question.")

    for query, strict, relaxed in attempts:
        pmids = search_pubmed_ids(query, strict_mode=strict, retmax=max_results, min_year=min_year)
        if pmids:
            articles = fetch_article_details(pmids)
            for article in articles:
                text = article.get("abstract", "")
                article["abstract_truncated"] = len(text) > abstract_max_chars
                if article["abstract_truncated"]:
                    article["abstract"] = text[:abstract_max_chars].rstrip() + " ..."
            return {
                "search_query": query,
                "high_evidence_filter": strict,
                "relaxations": relaxed,
                "article_count": len(articles),
                "articles": articles,
            }
    return {"search_query": attempts[-1][0], "high_evidence_filter": False,
            "relaxations": attempts[-1][2], "article_count": 0, "articles": []}
