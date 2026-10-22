"""Find the Jan Aushadhi generic substitute for a branded (or generic) medicine name.

Matching uses fuzzy string similarity plus a substring bonus (so "Atorlip 10" matches
"Atorlip 10 Tablet"). If ``rapidfuzz`` is installed it is used for speed; otherwise the
standard-library ``difflib`` is used with a cheap pre-filter.
"""

from __future__ import annotations

import difflib
import heapq
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .config import DEFAULT_DB_PATH

try:  # optional accelerator
    from rapidfuzz import fuzz as _rf_fuzz
    from rapidfuzz import process as _rf_process
except ImportError:  # pragma: no cover - exercised implicitly when rapidfuzz is absent
    _rf_fuzz = None
    _rf_process = None

DEFAULT_THRESHOLD = 85.0
MIN_SUBSTRING_LEN = 4  # queries this short or shorter never get the substring bonus ("met" vs "metformin")
CANDIDATE_POOL = 25
FIRST_WORD_MIN_SIMILARITY = 0.8

_WS_RE = re.compile(r"\s+")
_MENTION_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*|\d+(?:\.\d+)?")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

# Ordinary words that also occur in brand/product names; never treated as a drug mention.
_MENTION_STOP = frozenset("""
    tablet tablets capsule capsules injection injections syrup suspension solution cream ointment gel drops
    lotion powder pain relief joint patient patients doctor prescribe prescribed prescribing please what about
    with from have been that this give should could would their there where which while into over under than
    then them they also only some such very will take takes taking daily night morning plus forte advanced
    total complete care health fever cold cough allergy gold active super extra ultra max pro plus kids baby
    adult senior duo combi combo strong fast quick instant natural herbal protein calcium iron
""".split())

Entry = Tuple[str, int, str, str]  # (normalised text, record index, kind, original text)


def normalize(text: str) -> str:
    return _WS_RE.sub(" ", str(text).lower()).strip()


def _token_matches(token: str, query_token: str) -> bool:
    """``query_token`` is the start of ``token`` ("pantop" -> "pantoprazole", "500" -> "500mg"),
    but not when it is merely the first half of a hyphenated name ("atorlip" vs "atorlip-asp")."""
    if not token.startswith(query_token):
        return False
    return len(token) == len(query_token) or token[len(query_token)] not in "-/+"


def _word_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def compute_savings(jan_price: Optional[float], market_price: Optional[float]) -> Dict[str, Any]:
    """Price comparison between the Jan Aushadhi pack and the average branded pack."""
    jan = float(jan_price or 0.0)
    market = float(market_price or 0.0)
    if jan <= 0 or market <= 0:
        return {"price_status": "price_unavailable", "savings_amount": None, "savings_percent": None}
    amount = market - jan
    if amount <= 0:
        return {"price_status": "no_savings", "savings_amount": 0.0, "savings_percent": 0.0}
    return {
        "price_status": "savings",
        "savings_amount": round(amount, 2),
        "savings_percent": round(amount / market * 100, 1),
    }


class GenericFinder:
    """Index a medicine database once, then answer many lookups quickly."""

    def __init__(self, records: Sequence[Dict[str, Any]], threshold: float = DEFAULT_THRESHOLD):
        self.records = list(records)
        self.threshold = threshold
        self._entries: List[Entry] = []
        for idx, rec in enumerate(self.records):
            name = rec.get("generic_name", "")
            if name:
                self._entries.append((normalize(name), idx, "generic", name))
            for brand in rec.get("common_brands") or []:
                self._entries.append((normalize(brand), idx, "brand", brand))
        self._texts = [e[0] for e in self._entries]
        self._tokens = [t.split() for t in self._texts]

    @classmethod
    def from_json(cls, path: Optional[str | Path] = None, **kwargs: Any) -> "GenericFinder":
        path = Path(path) if path else DEFAULT_DB_PATH
        with open(path, "r", encoding="utf-8") as fh:
            return cls(json.load(fh), **kwargs)

    # ------------------------------------------------------------------ scoring
    def _fuzzy_scores(self, q: str) -> List[Tuple[int, float]]:
        """Top fuzzy candidates as (entry index, score 0-100)."""
        if _rf_process is not None:
            hits = _rf_process.extract(
                q, self._texts, scorer=_rf_fuzz.ratio, limit=CANDIDATE_POOL, score_cutoff=50
            )
            return [(index, float(score)) for _text, score, index in hits]

        matcher = difflib.SequenceMatcher(None)
        matcher.set_seq2(q)  # difflib caches statistics for seq2, so keep the query there
        scored: List[Tuple[float, int]] = []
        for i, text in enumerate(self._texts):
            matcher.set_seq1(text)
            if matcher.real_quick_ratio() < 0.6 or matcher.quick_ratio() < 0.6:
                continue
            scored.append((matcher.ratio() * 100, i))
        return [(i, s) for s, i in heapq.nlargest(CANDIDATE_POOL, scored)]

    def _score_entries(self, q: str) -> Dict[int, float]:
        scores: Dict[int, float] = {}
        if len(q) > MIN_SUBSTRING_LEN:
            q_tokens = q.split()
            first = q_tokens[0]
            for i, text in enumerate(self._texts):
                # Contained as-is ("atorlip 10" in "atorlip 10 tablet") or every query word is the
                # start of some word in the name ("metformin 500" -> "metformin ... 500mg").
                contained = q in text or all(
                    any(_token_matches(tok, qt) for tok in self._tokens[i]) for qt in q_tokens
                )
                if contained:
                    # 88-100: closer to the whole name is better; names starting with the query win ties
                    score = 88.0 + 8.0 * min(1.0, len(q) / len(text))
                    if text.startswith(first):
                        score += 4.0
                    scores[i] = score
        q_first = q.split()[0]
        for i, score in self._fuzzy_scores(q):
            # Long shared boilerplate ("... 2mg injection") must not make different brands look alike:
            # the leading word (usually the brand or drug name) has to be similar too.
            if _word_similarity(q_first, self._tokens[i][0]) < FIRST_WORD_MIN_SIMILARITY:
                continue
            scores[i] = max(scores.get(i, 0.0), score)
        return scores

    def _rank_records(self, query: str) -> List[Tuple[float, Entry]]:
        """Best-scoring entry per record, best record first."""
        q = normalize(query)
        if not q:
            return []
        best: Dict[int, Tuple[float, Entry]] = {}
        for i, score in self._score_entries(q).items():
            entry = self._entries[i]
            rec_idx = entry[1]
            if rec_idx not in best or score > best[rec_idx][0]:
                best[rec_idx] = (score, entry)
        return sorted(best.values(), key=lambda t: (-t[0], len(t[1][0])))

    # ------------------------------------------------------------------ free text
    def _mention_vocabulary(self) -> frozenset:
        """Words that can name a drug here: ingredient words of generics + first word of brands."""
        vocab = getattr(self, "_vocab_cache", None)
        if vocab is None:
            words = set()
            for _text, _idx, kind, original in self._entries:
                if kind == "generic":
                    words.update(w for w in re.findall(r"[a-z]+", original.lower()) if len(w) >= 5)
                else:
                    first = re.findall(r"[a-z]+", original.lower())[:1]
                    words.update(w for w in first if len(w) >= 4)
            vocab = self._vocab_cache = frozenset(words - _MENTION_STOP)
        return vocab

    def extract_drug_mentions(self, text: str, limit: int = 5) -> List[str]:
        """Deterministically pull drug-name candidates out of a sentence.

        "Prescribe Diclofenac 50 for joint pain" -> ["Diclofenac 50"]. A number directly after a
        name is kept as its strength. Words must exist in the database vocabulary, so ordinary
        English words are ignored.
        """
        tokens = _MENTION_TOKEN_RE.findall(text or "")
        vocab = self._mention_vocabulary()
        found: List[str] = []
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token.lower() in vocab:
                parts = [token]
                if i + 1 < len(tokens) and _NUMBER_RE.fullmatch(tokens[i + 1]):
                    parts.append(tokens[i + 1])
                    i += 1
                mention = " ".join(parts)
                if mention.lower() not in (m.lower() for m in found):
                    found.append(mention)
            i += 1
        return found[:limit]

    # ------------------------------------------------------------------ results
    def _describe(self, score: float, entry: Entry) -> Dict[str, Any]:
        _text, rec_idx, kind, original = entry
        rec = self.records[rec_idx]
        jan = rec.get("jan_price")
        market = rec.get("market_avg_price")
        return {
            "generic_name": rec.get("generic_name"),
            "unit_size": rec.get("unit_size"),
            "matched_on": kind,
            "matched_text": original,
            "match_score": round(score, 1),
            "jan_aushadhi_price": float(jan) if jan else None,
            "market_average_price": float(market) if market else None,
            "example_brands": list(rec.get("common_brands") or [])[:5],
            **compute_savings(jan, market),
        }

    @staticmethod
    def _message(match: Dict[str, Any]) -> str:
        name, unit = match["generic_name"], match.get("unit_size") or "pack"
        status = match["price_status"]
        if status == "savings":
            return (
                f"Switch available: Jan Aushadhi '{name}' ({unit}) costs "
                f"₹{match['jan_aushadhi_price']:.2f} vs a typical ₹{match['market_average_price']:.2f} "
                f"for branded versions. Save ₹{match['savings_amount']:.2f} "
                f"({match['savings_percent']:.0f}%) per pack."
            )
        if status == "no_savings":
            return f"Jan Aushadhi '{name}' exists but is not cheaper than the typical brand."
        return f"Jan Aushadhi lists '{name}' ({unit}), but its price comparison is unavailable."

    def search(self, query: str, limit: int = 3) -> Dict[str, Any]:
        """Look up ``query`` (brand or generic name) and return the best substitute."""
        ranked = self._rank_records(query)
        if not ranked or ranked[0][0] < self.threshold:
            closest = [
                {"name": entry[3], "generic_name": self.records[entry[1]].get("generic_name"), "score": round(s, 1)}
                for s, entry in ranked[:limit]
            ]
            return {
                "found": False,
                "query": query,
                "closest": closest,
                "message": f"No direct Jan Aushadhi substitute found for '{query}'.",
            }

        match = self._describe(*ranked[0])
        alternatives = [
            self._describe(s, e) for s, e in ranked[1 : 1 + limit] if s >= self.threshold
        ]
        return {
            "found": True,
            "query": query,
            "match": match,
            "alternatives": alternatives,
            "message": self._message(match),
        }


def search_jan_aushadhi(query_drug: str, medicine_database: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Convenience wrapper: one-off search over an in-memory database."""
    return GenericFinder(medicine_database).search(query_drug)
