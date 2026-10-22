"""Clean and merge medicine databases (typos, device brands, price/savings consistency)."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

# 1. Typo corrections found in the Jan Aushadhi source data (matched as whole words).
TYPO_MAP = {
    "Inection": "Injection",
    "Hydrchloride": "Hydrochloride",
    "Opthalmic": "Ophthalmic",
    "Opthlamic": "Ophthalmic",
    "Vildaglipitin": "Vildagliptin",
    "Glimipride": "Glimepiride",
    "Isosorbidemononitrate": "Isosorbide Mononitrate",
    "Vitamine": "Vitamin",
    "Inhalent": "Inhalant",
    "Tabelts": "Tablets",
}
_TYPO_PATTERNS = [(re.compile(rf"\b{re.escape(bad)}\b", re.IGNORECASE), good) for bad, good in TYPO_MAP.items()]

# 2. Surgical / device items: pharma brands (e.g. "Augmentin") do not apply to these.
DEVICE_KEYWORDS = [
    "Catheter", "Suture", "Needle", "Syringe", "Bandage", "Diaper", "Mask", "Gloves", "Cannula",
    "Tube", "Set", "Kit", "Strip", "Lancet", "Blade", "Monitor", "Support", "Belt", "Pouch",
    "Vaporizer", "Thermometer", "Cotton", "Gauze", "Tape", "Plaster", "Dressings", "Stocking",
    "Urine Pot", "Bedpan", "Exerciser", "Cup", "Condom", "Napkin", "Pad", "Swab",
]
# Whole-word match (optional plural "s"), so "Set" no longer matches "OndanSETron" or "Tape" "TAPEntadol".
_DEVICE_RE = re.compile(r"\b(?:%s)s?\b" % "|".join(re.escape(k) for k in DEVICE_KEYWORDS), re.IGNORECASE)
# A drug strength ("2mg", "500 mcg", "5%") means it is a medicine even if it contains a device word
# (e.g. "Nicotine 2mg Oral Disintegrating Strips").
_STRENGTH_RE = re.compile(r"\d+(?:\.\d+)?\s?(?:mg|mcg|µg|iu|%)", re.IGNORECASE)
# Likewise a pharmaceutical dosage form ("Throat Spray (... Pine Needle oil ...)") means a medicine.
_FORM_RE = re.compile(
    r"\b(?:tablet|capsule|injection|syrup|ointment|drop|solution|suspension|powder|lotion|spray|gel|oil|extract)s?\b",
    re.IGNORECASE,
)


def fix_typos(text: Any) -> Any:
    if not isinstance(text, str):
        return text
    for pattern, good in _TYPO_PATTERNS:
        text = pattern.sub(good, text)
    return text


def is_device(generic_name: str) -> bool:
    """True for surgical/consumable items (as opposed to medicines)."""
    if not _DEVICE_RE.search(generic_name):
        return False
    return not (_STRENGTH_RE.search(generic_name) or _FORM_RE.search(generic_name))


def recompute_pricing(record: Dict[str, Any]) -> Dict[str, str]:
    """Return corrected ``savings_alert`` / ``savings_percentage`` for a record.

    The government list has no MRP for ~16% of items (price 0). Treating 0 as a real price
    produced bogus "Save ₹X (100%)" alerts, so those are reported as unavailable instead.
    """
    jan = float(record.get("jan_price") or 0.0)
    market = float(record.get("market_avg_price") or 0.0)

    if jan <= 0:
        return {"savings_alert": "Price Unavailable", "savings_percentage": "N/A"}
    if market <= 0:
        return {"savings_alert": "N/A", "savings_percentage": "N/A"}
    if market > jan:
        saving = market - jan
        percent = int(saving / market * 100)
        return {"savings_alert": f"Save ₹{int(saving)} ({percent}%)", "savings_percentage": f"{percent}%"}
    return {"savings_alert": "No savings", "savings_percentage": "0%"}


def clean_record(record: Dict[str, Any]) -> Dict[str, Any]:
    rec = copy.deepcopy(record)
    rec["generic_name"] = fix_typos(rec.get("generic_name", ""))
    if is_device(rec["generic_name"]):
        rec["common_brands"] = []
    else:
        rec["common_brands"] = list(rec.get("common_brands") or [])
    rec.update(recompute_pricing(rec))
    return rec


def clean_records(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [clean_record(r) for r in records]


def _key(record: Dict[str, Any]) -> str:
    return str(record.get("generic_name", "")).lower().strip()


def merge_records(
    primary: Sequence[Dict[str, Any]], secondary: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Keep every ``primary`` record and add ``secondary`` records whose generic name is new."""
    seen = {_key(r) for r in primary}
    extras = [r for r in secondary if _key(r) not in seen]
    return list(primary) + extras


def load_json(path: str | Path) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(records: Sequence[Dict[str, Any]], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(list(records), fh, indent=2, ensure_ascii=False)
    return path


def build_clean_database(
    primary_path: str | Path, output_path: str | Path, secondary_path: Optional[str | Path] = None
) -> Dict[str, int]:
    """Load, clean, optionally merge a second DB, and write the result. Returns summary counts."""
    primary = clean_records(load_json(primary_path))
    total_primary = len(primary)
    merged = primary
    added = 0
    if secondary_path:
        merged = merge_records(primary, clean_records(load_json(secondary_path)))
        added = len(merged) - total_primary
    save_json(merged, output_path)
    return {"primary_records": total_primary, "added_from_secondary": added, "total_records": len(merged)}
