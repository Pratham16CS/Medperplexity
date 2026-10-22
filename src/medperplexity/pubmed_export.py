"""Search PubMed by author(s) and topic(s) and export the results to Excel."""

from __future__ import annotations

import logging
import re
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import pubmed

log = logging.getLogger(__name__)

COLUMNS = [
    "PMID", "Title", "Abstract", "Authors", "Journal", "Keywords",
    "MeSH_Terms", "DOI", "Publication_Date", "URL", "Affiliations",
]

_ILLEGAL_XLSX_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def format_author(name: str) -> str:
    """Convert "Anthony Fauci" to PubMed's "Fauci A" form (already-formatted names pass through).

    >>> format_author("Anthony Fauci")
    'Fauci A'
    >>> format_author("Fauci AS")
    'Fauci AS'
    """
    parts = name.replace(",", " ").split()
    if len(parts) < 2:
        return name.strip()
    last_token = parts[-1]
    if last_token.isupper() and len(last_token) <= 3:  # e.g. "Fauci AS" is already PubMed style
        return " ".join(parts)
    return f"{parts[-1]} {parts[0][0].upper()}"


def build_query(
    authors: Sequence[str] = (),
    topics: Sequence[str] = (),
    start: Optional[str] = None,
    end: Optional[str] = None,
    date_field: str = "Date - Create",
) -> str:
    """Build a PubMed query: (any author) AND (any topic) AND date range."""
    clauses: List[str] = []
    if authors:
        clauses.append("(" + " OR ".join(f"{format_author(a)}[Author]" for a in authors) + ")")
    if topics:
        clauses.append("(" + " OR ".join(f"{t}[Title/Abstract]" for t in topics) + ")")
    if start or end:
        clauses.append(f'("{start or "1800/01/01"}"[{date_field}] : "{end or "3000"}"[{date_field}])')
    if not clauses:
        raise ValueError("Provide at least one author, topic or date range.")
    return " AND ".join(clauses)


def _row(parsed: Dict[str, Any]) -> Dict[str, str]:
    abstract = parsed["abstract"]
    return {
        "PMID": parsed["pmid"],
        "Title": parsed["title"],
        "Abstract": "" if abstract == "No Abstract Available." else abstract,
        "Authors": ", ".join(parsed["authors"]),
        "Journal": parsed["journal"],
        "Keywords": ", ".join(parsed["keywords"]),
        "MeSH_Terms": ", ".join(parsed["mesh_terms"]),
        "DOI": parsed["doi"],
        "Publication_Date": parsed["pub_date"],
        "URL": parsed["url"],
        "Affiliations": "; ".join(parsed["affiliations"]),
    }


def search_ids(query: str, retmax: int = 20) -> List[str]:
    """ESearch without any evidence filter (returns PMIDs, newest-relevance first)."""
    entrez = pubmed._entrez()

    def _do() -> Any:
        with closing(entrez.esearch(db="pubmed", term=query, retmax=retmax)) as handle:
            return entrez.read(handle)

    return [str(i) for i in pubmed._call_with_retry(_do).get("IdList", [])]


def records_to_dataframe(parsed_articles: Sequence[Dict[str, Any]]):
    import pandas as pd

    return pd.DataFrame([_row(a) for a in parsed_articles], columns=COLUMNS)


def export_to_excel(df, path: str | Path) -> Path:
    """Write ``df`` to ``path``, stripping control characters that Excel cannot store."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = df.copy()
    for col in clean.columns:
        clean[col] = clean[col].map(
            lambda v: _ILLEGAL_XLSX_CHARS.sub("", v) if isinstance(v, str) else v
        )
    clean.to_excel(path, index=False)
    return path


def run_export(
    authors: Sequence[str],
    topics: Sequence[str],
    start: Optional[str],
    end: Optional[str],
    retmax: int,
    out: str | Path,
) -> Dict[str, Any]:
    """Full pipeline: build query -> search -> batched fetch -> parse -> Excel."""
    query = build_query(authors, topics, start, end)
    log.info("PubMed query: %s", query)
    ids = search_ids(query, retmax=retmax)
    parsed = [pubmed.parse_article(a) for a in pubmed.fetch_pubmed_articles(ids)]
    df = records_to_dataframe(parsed)
    path = export_to_excel(df, out)
    return {"query": query, "records": len(df), "output": str(path)}
