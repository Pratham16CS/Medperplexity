"""Find Jan Aushadhi catalogue matches with conservative formulation checks.

Important:
- Fuzzy matching is for catalogue discovery, not clinical equivalence.
- Strength, ingredient, dosage form, and release-formulation mismatches
  are filtered where they can be identified from the available text.
- Ambiguous matches require clarification instead of a switch recommendation.
"""

from __future__ import annotations

import difflib
import heapq
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .config import DEFAULT_DB_PATH

try:
    from rapidfuzz import fuzz as _rf_fuzz
    from rapidfuzz import process as _rf_process
except ImportError:
    _rf_fuzz = None
    _rf_process = None


DEFAULT_THRESHOLD = 85.0
MIN_SUBSTRING_LEN = 4
CANDIDATE_POOL = 25
FIRST_WORD_MIN_SIMILARITY = 0.8

_WS_RE = re.compile(r"\s+")
_MENTION_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*|\d+(?:\.\d+)?")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

_MENTION_STOP = frozenset("""
    tablet tablets capsule capsules injection injections syrup suspension
    solution cream ointment gel drops lotion powder pain relief joint patient
    patients doctor prescribe prescribed prescribing please what about with
    from have been that this give should could would their there where which
    while into over under than then them they also only some such very will
    take takes taking daily night morning plus forte advanced total complete
    care health fever cold cough allergy gold active super extra ultra max pro
    kids baby adult senior duo combi combo strong fast quick instant natural
    herbal protein calcium iron
""".split())

Entry = Tuple[str, int, str, str]


def normalize(text: str) -> str:
    """Normalize whitespace and case for matching."""
    return _WS_RE.sub(" ", str(text).lower()).strip()


def _token_matches(token: str, query_token: str) -> bool:
    """Match a token prefix without accepting a hyphenated-name fragment."""
    if not token.startswith(query_token):
        return False
    return (
        len(token) == len(query_token)
        or token[len(query_token)] not in "-/+"
    )


def _word_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def compute_savings(
    jan_price: Optional[float],
    market_price: Optional[float],
) -> Dict[str, Any]:
    """Calculate a catalogue price difference, not a clinical recommendation."""
    jan = float(jan_price or 0.0)
    market = float(market_price or 0.0)

    if jan <= 0 or market <= 0:
        return {
            "price_status": "price_unavailable",
            "savings_amount": None,
            "savings_percent": None,
        }

    amount = market - jan

    if amount <= 0:
        return {
            "price_status": "no_savings",
            "savings_amount": 0.0,
            "savings_percent": 0.0,
        }

    return {
        "price_status": "savings",
        "savings_amount": round(amount, 2),
        "savings_percent": round(amount / market * 100, 1),
    }


# These patterns are intentionally conservative. Text-based matching cannot
# establish clinical equivalence or reliably interpret every brand abbreviation.
_RELEASE_PATTERNS = {
    "prolonged_release": re.compile(
        r"\b(prolonged|extended|sustained)\s*[- ]?\s*release\b"
        r"|\b(sr|xr|er|pr|od)\b",
        re.I,
    ),
    "gastro_resistant": re.compile(
        r"\b(gastro[- ]?resistant|enteric[- ]?coated|delayed[- ]?release)\b",
        re.I,
    ),
    "immediate_release": re.compile(
        r"\b(immediate[- ]?release|instant[- ]?release|ir)\b",
        re.I,
    ),
}

_FORM_PATTERNS = {
    "tablet": re.compile(r"\btablets?\b", re.I),
    "capsule": re.compile(r"\bcapsules?\b", re.I),
    "injection": re.compile(r"\binjections?\b", re.I),
    "oral_liquid": re.compile(r"\b(syrup|suspension|oral solution)\b", re.I),
    "topical": re.compile(r"\b(cream|ointment|gel|lotion)\b", re.I),
}

_STRENGTH_RE = re.compile(
    r"(?<!\w)(\d+(?:\.\d+)?)\s*(mcg|µg|mg|g|ml|iu|%)\b",
    re.I,
)

_INGREDIENT_STOP = {
    "hydrochloride", "phosphate", "sodium", "potassium", "calcium",
    "sulphate", "sulfate", "maleate", "fumarate", "acetate", "nitrate",
    "bromide", "diethylamine", "tablets", "tablet", "capsules", "capsule",
    "injection", "ip", "bp", "usp", "prolonged", "release", "extended",
    "sustained", "gastro", "resistant", "delayed", "enteric", "coated",
    "oral", "topical", "cream", "ointment", "gel", "solution", "syrup",
    "suspension", "mg", "mcg", "ml", "iu", "and", "with", "plus",
}


def _strengths(text: str) -> List[Tuple[str, str]]:
    """Extract number/unit pairs without assuming unit conversions."""
    result = []

    for value, unit in _STRENGTH_RE.findall(text or ""):
        number_float = float(value)
        number = (
            str(number_float).rstrip("0").rstrip(".")
            if "." in str(number_float)
            else str(int(number_float))
        )
        result.append(
            (number, unit.lower().replace("µg", "mcg"))
        )

    return result


def _release_profile(text: str) -> Optional[str]:
    """Return a recognized release profile, or None if not identified."""
    matches = [
        name
        for name, pattern in _RELEASE_PATTERNS.items()
        if pattern.search(text or "")
    ]

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return "conflicting"
    return None


def _dosage_form(text: str) -> Optional[str]:
    matches = [
        name
        for name, pattern in _FORM_PATTERNS.items()
        if pattern.search(text or "")
    ]

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return "conflicting"
    return None


def _ingredient_terms(text: str) -> set[str]:
    """Approximate ingredient-like words for conservative text filtering only."""
    text = (text or "").lower()
    text = _STRENGTH_RE.sub(" ", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\b", " ", text)
    tokens = re.findall(r"[a-z]+", text)

    return {
        token
        for token in tokens
        if len(token) >= 5 and token not in _INGREDIENT_STOP
    }


def _candidate_compatible(
    query: str,
    record: Dict[str, Any],
    *,
    matched_on_brand: bool = False,
    exact_brand_alias: bool = False,
) -> Tuple[bool, List[str]]:
    """Reject detectable text mismatches and return reasons for rejection."""
    reasons: List[str] = []
    candidate = str(record.get("generic_name") or "")

    query_strengths = _strengths(query)
    candidate_strengths = _strengths(candidate)

    # Strengths in combination products may be listed in a different order
    # in the brand alias and generic ingredient description (e.g. 5mg/10mg
    # vs montelukast 10mg + levocetirizine 5mg). Compare the multiset, not
    # the order; repeated strengths remain significant.
    if query_strengths and candidate_strengths:
        # An exact catalogue brand alias can include pack volume (e.g. 100ml)
        # while the generic description states active concentration (e.g. 1.53g/5ml).
        # The alias-to-record relationship is explicit in the catalogue; don't
        # misread packaging volume as an ingredient strength. Fuzzy brand matches
        # still undergo the normal strength check.
        if sorted(query_strengths) != sorted(candidate_strengths) and not exact_brand_alias:
            reasons.append("strength_or_combination_mismatch")

    query_form = _dosage_form(query)
    candidate_form = _dosage_form(candidate)

    if (
        query_form
        and query_form != "conflicting"
        and candidate_form
        and candidate_form != query_form
    ):
        reasons.append("dosage_form_mismatch")

    if query_form == "conflicting" or candidate_form == "conflicting":
        reasons.append("dosage_form_ambiguous")

    query_release = _release_profile(query)
    candidate_release = _release_profile(candidate)

    if (
        query_release
        and query_release != "conflicting"
        and candidate_release
        and candidate_release != query_release
    ):
        reasons.append("release_formulation_mismatch")

    if (
        query_release == "conflicting"
        or candidate_release == "conflicting"
    ):
        reasons.append("release_formulation_ambiguous")

    # A brand query (e.g. "Telma 40") will not share ingredient words with
    # the generic catalogue name ("Telmisartan Tablets IP 40mg"). The brand-to-
    # generic association is already supplied by this catalogue record, so do
    # not misclassify the brand name as an ingredient mismatch. Strength, form,
    # and release checks above still apply.
    if not matched_on_brand:
        query_terms = _ingredient_terms(query)
        candidate_terms = _ingredient_terms(candidate)
        common_terms = query_terms & candidate_terms

        if query_terms and not common_terms:
            reasons.append("ingredient_mismatch")
        elif query_terms and common_terms and len(query_terms) == 1:
            if candidate_terms - query_terms:
                reasons.append("possible_combination_mismatch")

    return not reasons, reasons


class GenericFinder:
    """Index a medicine database once, then answer catalogue lookups."""

    def __init__(
        self,
        records: Sequence[Dict[str, Any]],
        threshold: float = DEFAULT_THRESHOLD,
    ):
        self.records = list(records)
        self.threshold = threshold
        self._entries: List[Entry] = []

        for index, record in enumerate(self.records):
            name = record.get("generic_name", "")

            if name:
                self._entries.append(
                    (normalize(name), index, "generic", name)
                )

            for brand in record.get("common_brands") or []:
                self._entries.append(
                    (normalize(brand), index, "brand", brand)
                )

        self._texts = [entry[0] for entry in self._entries]
        self._tokens = [text.split() for text in self._texts]

    @classmethod
    def from_json(
        cls,
        path: Optional[str | Path] = None,
        **kwargs: Any,
    ) -> "GenericFinder":
        path = Path(path) if path else DEFAULT_DB_PATH

        with open(path, "r", encoding="utf-8") as file:
            return cls(json.load(file), **kwargs)

    def _fuzzy_scores(self, query: str) -> List[Tuple[int, float]]:
        """Return fuzzy candidates as (entry index, score 0-100)."""
        if _rf_process is not None:
            hits = _rf_process.extract(
                query,
                self._texts,
                scorer=_rf_fuzz.ratio,
                limit=CANDIDATE_POOL,
                score_cutoff=50,
            )
            return [
                (index, float(score))
                for _text, score, index in hits
            ]

        matcher = difflib.SequenceMatcher(None)
        matcher.set_seq2(query)
        scored: List[Tuple[float, int]] = []

        for index, text in enumerate(self._texts):
            matcher.set_seq1(text)

            if (
                matcher.real_quick_ratio() < 0.6
                or matcher.quick_ratio() < 0.6
            ):
                continue

            scored.append((matcher.ratio() * 100, index))

        return [
            (index, score)
            for score, index in heapq.nlargest(CANDIDATE_POOL, scored)
        ]

    def _score_entries(self, query: str) -> Dict[int, float]:
        scores: Dict[int, float] = {}

        if len(query) > MIN_SUBSTRING_LEN:
            query_tokens = query.split()
            first = query_tokens[0]

            for index, text in enumerate(self._texts):
                contained = query in text or all(
                    any(
                        _token_matches(token, query_token)
                        for token in self._tokens[index]
                    )
                    for query_token in query_tokens
                )

                if contained:
                    score = 88.0 + 8.0 * min(
                        1.0, len(query) / max(len(text), 1)
                    )

                    if text.startswith(first):
                        score += 4.0

                    scores[index] = score

        query_first = query.split()[0]

        for index, score in self._fuzzy_scores(query):
            if (
                _word_similarity(
                    query_first,
                    self._tokens[index][0],
                )
                < FIRST_WORD_MIN_SIMILARITY
            ):
                continue

            scores[index] = max(scores.get(index, 0.0), score)

        return scores

    def _rank_records(
        self,
        query: str,
    ) -> List[Tuple[float, Entry]]:
        """Return the best-scoring entry for each record."""
        normalized_query = normalize(query)

        if not normalized_query:
            return []

        best: Dict[int, Tuple[float, Entry]] = {}

        for index, score in self._score_entries(normalized_query).items():
            entry = self._entries[index]
            record_index = entry[1]

            if (
                record_index not in best
                or score > best[record_index][0]
            ):
                best[record_index] = (score, entry)

        return sorted(
            best.values(),
            key=lambda item: (-item[0], len(item[1][0])),
        )

    def _mention_vocabulary(self) -> frozenset:
        """Words that can identify a drug in the loaded catalogue."""
        vocabulary = getattr(self, "_vocab_cache", None)

        if vocabulary is None:
            words = set()

            for _text, _index, kind, original in self._entries:
                if kind == "generic":
                    words.update(
                        word
                        for word in re.findall(
                            r"[a-z]+", original.lower()
                        )
                        if len(word) >= 5
                    )
                else:
                    first = re.findall(r"[a-z]+", original.lower())[:1]
                    words.update(
                        word for word in first if len(word) >= 4
                    )

            vocabulary = frozenset(words - _MENTION_STOP)
            self._vocab_cache = vocabulary

        return vocabulary

    def extract_drug_mentions(
        self,
        text: str,
        limit: int = 5,
    ) -> List[str]:
        """Extract likely medicine names from a sentence."""
        tokens = _MENTION_TOKEN_RE.findall(text or "")
        vocabulary = self._mention_vocabulary()
        found: List[str] = []
        index = 0

        while index < len(tokens):
            token = tokens[index]

            if token.lower() in vocabulary:
                parts = [token]

                if (
                    index + 1 < len(tokens)
                    and _NUMBER_RE.fullmatch(tokens[index + 1])
                ):
                    parts.append(tokens[index + 1])
                    index += 1

                mention = " ".join(parts)

                if mention.lower() not in (
                    item.lower() for item in found
                ):
                    found.append(mention)

            index += 1

        return found[:limit]

    def _describe(
        self,
        score: float,
        entry: Entry,
    ) -> Dict[str, Any]:
        _text, record_index, kind, original = entry
        record = self.records[record_index]
        jan_price = record.get("jan_price")
        market_price = record.get("market_avg_price")

        return {
            "generic_name": record.get("generic_name"),
            "unit_size": record.get("unit_size"),
            "matched_on": kind,
            "matched_text": original,
            "match_score": round(score, 1),
            "jan_aushadhi_price": (
                float(jan_price) if jan_price else None
            ),
            "market_average_price": (
                float(market_price) if market_price else None
            ),
            "example_brands": list(
                record.get("common_brands") or []
            )[:5],
            **compute_savings(jan_price, market_price),
        }

    @staticmethod
    def _message(match: Dict[str, Any]) -> str:
        name = match["generic_name"]
        unit = match.get("unit_size") or "pack"
        status = match["price_status"]

        if status == "savings":
            return (
                f"Catalogue price comparison: Jan Aushadhi '{name}' "
                f"({unit}) is ₹{match['jan_aushadhi_price']:.2f} "
                f"versus a listed typical brand price of "
                f"₹{match['market_average_price']:.2f}. "
                f"The estimated difference is "
                f"₹{match['savings_amount']:.2f} "
                f"({match['savings_percent']:.1f}%) per pack. "
                "Save estimate is catalogue-based; this does not establish clinical equivalence."
            )

        if status == "no_savings":
            return (
                f"Jan Aushadhi lists '{name}', but it is not cheaper "
                "than the listed typical brand price."
            )

        return (
            f"Jan Aushadhi lists '{name}' ({unit}), but a price "
            "comparison is unavailable."
        )

    def search(
        self,
        query: str,
        limit: int = 3,
    ) -> Dict[str, Any]:
        """Find catalogue candidates while rejecting obvious text mismatches."""
        ranked = self._rank_records(query)

        if not ranked or ranked[0][0] < self.threshold:
            closest = [
                {
                    "name": entry[3],
                    "generic_name": self.records[entry[1]].get(
                        "generic_name"
                    ),
                    "score": round(score, 1),
                }
                for score, entry in ranked[:limit]
            ]

            return {
                "found": False,
                "query": query,
                "closest": closest,
                "message": (
                    f"No direct Jan Aushadhi substitute or catalogue match "
                    f"found for '{query}'."
                ),
                "ambiguous": False,
                "confidence": "low",
            }

        high_ranked = [
            (score, entry)
            for score, entry in ranked
            if score >= self.threshold
        ][:max(limit * 5, 15)]

        compatible = []

        for score, entry in high_ranked:
            record = self.records[entry[1]]
            exact_brand_alias = (
                entry[2] == "brand"
                and normalize(query) == normalize(entry[3])
            )
            is_compatible, reasons = _candidate_compatible(
                query,
                record,
                matched_on_brand=(entry[2] == "brand"),
                exact_brand_alias=exact_brand_alias,
            )

            if is_compatible:
                compatible.append((score, entry))

        if not compatible:
            return {
                "found": False,
                "query": query,
                "closest": [
                    {
                        "name": entry[3],
                        "generic_name": self.records[entry[1]].get(
                            "generic_name"
                        ),
                        "score": round(score, 1),
                        "reasons": _candidate_compatible(
                            query, self.records[entry[1]],
                            matched_on_brand=(entry[2] == "brand"),
                        )[1],
                    }
                    for score, entry in high_ranked[:limit]
                ],
                "message": (
                    "No candidate passed the ingredient, strength, "
                    "dosage-form and formulation text checks."
                ),
                "ambiguous": True,
                "confidence": "low",
                "clarification": (
                    "Confirm the exact active ingredient(s), strength, "
                    "dosage form and release formulation before "
                    "comparing prices."
                ),
            }

        query_release = _release_profile(query)

        release_profiles = {
            _release_profile(
                self.records[entry[1]].get("generic_name", "")
            )
            for _score, entry in compatible
        }
        release_profiles.discard(None)

        # Do not silently choose a release-specific product if the query
        # does not state its release formulation.
        if query_release is None and release_profiles:
            return {
                "found": False,
                "query": query,
                "closest": [
                    {
                        "name": entry[3],
                        "generic_name": self.records[entry[1]].get(
                            "generic_name"
                        ),
                        "score": round(score, 1),
                    }
                    for score, entry in compatible[:limit]
                ],
                "message": (
                    "The query omits release formulation, and a "
                    "release-specific catalogue candidate was found. "
                    "No substitute has been selected."
                ),
                "ambiguous": True,
                "confidence": "low",
                "clarification": (
                    "Is the prescribed product immediate-release or "
                    "modified-release (for example SR, ER, XR, or "
                    "prolonged-release)?"
                ),
            }

        score, entry = compatible[0]
        match = self._describe(score, entry)
        match["clinical_equivalence"] = "not_established"
        match["formulation_check"] = "catalogue_screen_passed"

        alternatives = [
            self._describe(candidate_score, candidate_entry)
            for candidate_score, candidate_entry in compatible[
                1:1 + limit
            ]
        ]

        return {
            "found": True,
            "query": query,
            "match": match,
            "alternatives": alternatives,
            "message": self._message(match),
            "ambiguous": False,
            "confidence": "catalogue_match_only",
            "clinical_equivalence": "not_established",
            "warning": (
                "Catalogue similarity and price data do not establish "
                "clinical interchangeability. Verify the exact product "
                "with a pharmacist."
            ),
        }


def search_jan_aushadhi(
    query_drug: str,
    medicine_database: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Convenience wrapper for a one-off in-memory catalogue search."""
    return GenericFinder(medicine_database).search(query_drug)