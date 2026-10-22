"""Deterministic patient-vs-order checks that run BEFORE any LLM and cannot be overridden by one.

Scope is deliberately small and conservative: documented allergies (including well-known class
cross-sensitivities), duplicate therapy, and a small set of high-priority medication interactions. The
catalogues are *not exhaustive*. Flags are decision-support prompts for clinician review, not a substitute
for a complete interaction checker or clinical judgement.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

# Members are matched as whole lowercase words / phrases.
DRUG_CLASSES: Dict[str, List[str]] = {
    "penicillins": ["penicillin", "amoxicillin", "amoxycillin", "ampicillin", "cloxacillin", "flucloxacillin",
                    "piperacillin", "benzylpenicillin", "benzathine penicillin", "phenoxymethylpenicillin"],
    "cephalosporins": ["cephalexin", "cefalexin", "cefazolin", "cefuroxime", "cefixime", "cefpodoxime",
                       "ceftriaxone", "cefotaxime", "ceftazidime", "cefepime", "cefadroxil", "cefdinir"],
    "sulfonamides": ["sulfamethoxazole", "sulphamethoxazole", "cotrimoxazole", "co-trimoxazole", "sulfasalazine",
                     "sulphasalazine", "sulfadiazine"],
    "nsaids": ["aspirin", "diclofenac", "aceclofenac", "ibuprofen", "naproxen", "ketorolac", "indomethacin",
               "piroxicam", "meloxicam", "etoricoxib", "celecoxib", "nimesulide", "mefenamic acid", "ketoprofen"],
}
CLASS_ALIASES: Dict[str, str] = {
    "penicillin": "penicillins", "penicillins": "penicillins", "beta lactam": "penicillins",
    "cephalosporin": "cephalosporins", "cephalosporins": "cephalosporins",
    "sulfa": "sulfonamides", "sulpha": "sulfonamides", "sulfonamide": "sulfonamides", "sulfonamides": "sulfonamides",
    "nsaid": "nsaids", "nsaids": "nsaids", "anti-inflammatory": "nsaids", "anti inflammatory": "nsaids",
}

SEVERITY = {"info": 0, "approved": 0, "caution": 1, "blocked": 2}

_ALLERGY_KEYS = ("allergies", "allergy", "drug_allergies", "known_allergies")
_MEDICATION_KEYS = ("current_medications", "medications", "current_meds", "meds", "current_medication")
_CONDITION_KEYS = ("condition_tags", "conditions", "diagnoses", "problems")


def _norm(text: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9\- ]", " ", str(text).lower()).split())


def _first_value(patient: Dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in patient:
            return patient[key]
    return None


def as_list(value: Any) -> List[str]:
    """Allergies/medications may be a list, a comma string, or a list of dicts with a 'name'."""
    if value is None:
        return []
    if isinstance(value, str):
        value = re.split(r"[,;\n]+", value)
    out: List[str] = []
    for item in value if isinstance(value, (list, tuple, set)) else [value]:
        if isinstance(item, dict):
            item = item.get("name") or item.get("drug") or item.get("substance") or ""
        text = _norm(item)
        if text and text not in ("none", "nil", "nkda", "no known allergies", "no known drug allergies", "na", "n/a"):
            out.append(text)
    return out


def patient_conditions(patient: Dict[str, Any]) -> List[str]:
    return as_list(_first_value(patient, _CONDITION_KEYS))


def _drug_words(drug: str) -> List[str]:
    """Alphabetic words of a drug mention ("Diclofenac 50" -> ["diclofenac"])."""
    return [w for w in re.findall(r"[a-z][a-z\-]+", _norm(drug)) if len(w) > 2]


def _class_of(term: str) -> str:
    """Class a term names or belongs to ('' if none)."""
    if term in CLASS_ALIASES:
        return CLASS_ALIASES[term]
    for cls, members in DRUG_CLASSES.items():
        if any(term == m or term in m.split() and len(term) > 4 for m in members):
            return cls
    return ""


def _is_member(drug: str, cls: str) -> bool:
    words = set(_drug_words(drug)) | {_norm(drug)}
    return any(m in words or any(m == w for w in words) or m in _norm(drug) for m in DRUG_CLASSES.get(cls, []))


_NON_DISTINCTIVE_DRUG_WORDS = {
    "chloride", "sodium", "potassium", "calcium", "magnesium", "sulfate", "sulphate",
    "phosphate", "hydrochloride", "hcl", "acetate", "maleate", "fumarate", "succinate",
    "tartrate", "bromide", "tablet", "tablets", "capsule", "capsules", "oral", "solution",
    "supplement", "supplements", "mg", "mcg", "ml", "w", "sr", "er", "xr",
}


def _same_drug(a: str, b: str) -> bool:
    """Conservatively match the same active-drug name, ignoring strengths and common salt/form words.

    Avoid matching unrelated medicines merely because they share a formulation word (e.g. sodium chloride
    and potassium chloride). This remains a heuristic, not a pharmaceutical ingredient normalizer.
    """
    na, nb = _norm(a), _norm(b)
    if na == nb:
        return True
    wa = {w for w in _drug_words(a) if w not in _NON_DISTINCTIVE_DRUG_WORDS and not w.isdigit()}
    wb = {w for w in _drug_words(b) if w not in _NON_DISTINCTIVE_DRUG_WORDS and not w.isdigit()}
    return bool(wa & wb) or any(len(x) >= 6 and (x in y or y in x) for x in wa for y in wb)


# A deliberately small interaction set. Extend only with reviewed, well-supported rules and tests.
_ACEI_ARBS = {
    "ramipril", "lisinopril", "enalapril", "captopril", "perindopril", "benazepril",
    "losartan", "valsartan", "telmisartan", "candesartan", "olmesartan", "irbesartan",
}
_POTASSIUM_PRODUCTS = {
    "potassium chloride", "potassium citrate", "potassium supplement", "potassium supplements", "kcl",
}
_NSAIDS = set(DRUG_CLASSES["nsaids"])
_ANTICOAGULANTS = {"warfarin", "apixaban", "rivaroxaban", "dabigatran", "edoxaban"}
_TETRACYCLINES = {"doxycycline", "tetracycline", "minocycline"}
_MACROLIDES = {"clarithromycin", "erythromycin"}
_STATINS = {"simvastatin", "lovastatin"}


def _contains_any(text: str, names: set[str]) -> bool:
    normalized = _norm(text)
    return any(re.search(rf"(?<![a-z]){re.escape(name)}(?![a-z])", normalized) for name in names)


def _interaction_flags(drugs: Sequence[str], meds: Sequence[str]) -> List[Dict[str, str]]:
    """Flag selected high-priority combinations between orders and current meds, and within the order."""
    flags: List[Dict[str, str]] = []
    pairs = [(drug, med) for drug in drugs for med in meds]
    pairs += [(drugs[i], drugs[j]) for i in range(len(drugs)) for j in range(i + 1, len(drugs))]
    seen: set[tuple[str, str, str]] = set()
    for first, second in pairs:
        a, b = _norm(first), _norm(second)
        if not a or not b:
            continue
        rules = []
        if ((_contains_any(a, _POTASSIUM_PRODUCTS) and _contains_any(b, _ACEI_ARBS)) or
                (_contains_any(b, _POTASSIUM_PRODUCTS) and _contains_any(a, _ACEI_ARBS))):
            rules.append(("interaction_potassium_raas", "Potassium products combined with an ACE inhibitor or ARB can cause dangerous hyperkalemia; verify indication, renal function, and serum potassium."))
        if ((_contains_any(a, _ANTICOAGULANTS) and _contains_any(b, _NSAIDS)) or
                (_contains_any(b, _ANTICOAGULANTS) and _contains_any(a, _NSAIDS))):
            rules.append(("interaction_anticoagulant_nsaid", "An anticoagulant combined with an NSAID can increase bleeding risk; review alternatives and monitoring."))
        if ((_contains_any(a, _TETRACYCLINES) and _contains_any(b, {"isotretinoin"})) or
                (_contains_any(b, _TETRACYCLINES) and _contains_any(a, {"isotretinoin"}))):
            rules.append(("interaction_isotretinoin_tetracycline", "Isotretinoin combined with a tetracycline antibiotic may increase intracranial-hypertension risk; avoid unless a qualified prescriber confirms an appropriate plan."))
        if ((_contains_any(a, _MACROLIDES) and _contains_any(b, _STATINS)) or
                (_contains_any(b, _MACROLIDES) and _contains_any(a, _STATINS))):
            rules.append(("interaction_macrolide_statin", "Clarithromycin/erythromycin with simvastatin/lovastatin can increase myopathy/rhabdomyolysis risk; check the specific product guidance and alternatives."))
        for kind, detail in rules:
            key = (kind, *sorted((a, b)))
            if key in seen:
                continue
            seen.add(key)
            flags.append({"type": kind, "severity": "caution", "drug": first,
                          "detail": f"Potential interaction between '{first}' and '{second}'. {detail}"})
    return flags


def check_patient_flags(patient: Dict[str, Any], drugs: Sequence[str]) -> List[Dict[str, str]]:
    """Return advisory flags: ``{"type", "severity" (blocked|caution|info), "drug", "detail"}``."""
    flags: List[Dict[str, str]] = []
    if not isinstance(patient, dict) or not patient or "error" in patient:
        return flags
    allergy_raw = _first_value(patient, _ALLERGY_KEYS)
    allergies = as_list(allergy_raw)
    meds = as_list(_first_value(patient, _MEDICATION_KEYS))

    if allergy_raw is None:
        flags.append({"type": "allergy_data_missing", "severity": "info", "drug": "",
                      "detail": "No allergy history is on record for this patient; confirm allergies before prescribing."})

    for drug in drugs:
        for allergy in allergies:
            allergy_class = CLASS_ALIASES.get(allergy) or ""
            if allergy_class:                                    # allergy names a whole class ("penicillin", "sulfa")
                if _is_member(drug, allergy_class):
                    flags.append({"type": "allergy", "severity": "blocked", "drug": drug,
                                  "detail": f"Documented allergy to '{allergy}'; {drug} belongs to that class."})
                continue
            if _same_drug(drug, allergy):                        # the very same drug
                flags.append({"type": "allergy", "severity": "blocked", "drug": drug,
                              "detail": f"Documented allergy to '{allergy}'."})
                continue
            cls = _class_of(allergy)                             # allergic to one member: cross-reactivity possible
            if cls and _is_member(drug, cls):
                flags.append({"type": "allergy_cross_reactivity", "severity": "caution", "drug": drug,
                              "detail": f"Documented allergy to '{allergy}'; {drug} is in the same drug class "
                                        f"({cls}), so cross-reactivity is possible."})
        for med in meds:
            if _same_drug(drug, med):
                flags.append({"type": "duplicate_therapy", "severity": "caution", "drug": drug,
                              "detail": f"Patient is already taking '{med}'."})

    flags.extend(_interaction_flags(drugs, meds))
    return flags


# Names recognized by the rule-based planner. Keep interaction drugs here too, otherwise a
# no-LLM request such as "Potassium chloride supplement" may never reach the safety checks.
_KNOWN_DRUG_NAMES = set(m for members in DRUG_CLASSES.values() for m in members)
_KNOWN_DRUG_NAMES.update(_ACEI_ARBS)
_KNOWN_DRUG_NAMES.update(_POTASSIUM_PRODUCTS)
_KNOWN_DRUG_NAMES.update(_ANTICOAGULANTS)
_KNOWN_DRUG_NAMES.update(_TETRACYCLINES)
_KNOWN_DRUG_NAMES.update(_MACROLIDES)
_KNOWN_DRUG_NAMES.update(_STATINS)
_KNOWN_DRUG_NAMES.update({"isotretinoin", "warfarin", "apixaban", "rivaroxaban", "dabigatran", "edoxaban"})
_KNOWN_DRUG_NAMES = sorted(_KNOWN_DRUG_NAMES, key=len, reverse=True)
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z\-']*|\d+(?:\.\d+)?")


def extract_known_drugs(text: str) -> List[str]:
    """Extract known drug names from free text, preserving an immediately following strength.

    Longest names are matched first so "potassium chloride supplement" is recognized as
    potassium chloride rather than the generic word "potassium". This vocabulary is intentionally
    finite; it is not a general-purpose medication NER system.
    """
    raw = text or ""
    normalized = _norm(raw)
    found: List[tuple[int, str]] = []
    for name in _KNOWN_DRUG_NAMES:
        pattern = re.compile(rf"(?<![a-z]){re.escape(name)}(?![a-z])", re.IGNORECASE)
        for match in pattern.finditer(normalized):
            mention = name
            tail = normalized[match.end():]
            strength = re.match(r"\s+(\d+(?:\.\d+)?)\b", tail)
            if strength:
                mention = f"{name} {strength.group(1)}"
            found.append((match.start(), mention))
    # Preserve source order, deduplicate equivalent mentions, and avoid returning a shorter name
    # nested inside a longer name at the same position.
    found.sort(key=lambda item: (item[0], -len(item[1])))
    result: List[str] = []
    occupied_until = -1
    for position, mention in found:
        if position < occupied_until:
            continue
        key = mention.lower()
        if not any(existing.lower() == key for existing in result):
            result.append(mention)
        # A conservative span prevents e.g. "potassium" being added after "potassium chloride".
        base = mention.rsplit(" ", 1)[0] if mention.rsplit(" ", 1)[-1].replace(".", "", 1).isdigit() else mention
        occupied_until = max(occupied_until, position + len(base))
    return result


def worst_status(*statuses: str) -> str:
    """The most severe of several statuses (info/approved < caution < blocked).

    On a tie the first argument wins, so ``worst_status(llm_status, code_status)`` keeps the LLM's wording
    unless the software's verdict is strictly more severe.
    """
    best = None
    for status in statuses:
        if best is None or SEVERITY.get(status, 1) > SEVERITY.get(best, 1):
            best = status
    return best or "info"


def flags_status(flags: Sequence[Dict[str, str]]) -> str:
    return worst_status(*[f["severity"] for f in flags]) if flags else "info"
