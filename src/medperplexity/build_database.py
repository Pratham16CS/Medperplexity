"""Build ``medicines.json`` from the two raw CSV files.

Inputs
------
* ``jan_aushadhi.csv``    - official Jan Aushadhi (PMBJP) product list (generic name, pack, MRP).
* ``brand_medicines.csv`` - online-pharmacy catalogue (brand name, MRP, pack, salt composition).

What it does
------------
For every Jan Aushadhi product it finds the branded medicines that contain the *same active
ingredients at the same strengths in the same dosage form*, then compares prices.

Matching rules (all must hold):

1. **Ingredients** - identical set of active-ingredient words, after normalising spelling
   variants (Amoxycillin/Amoxicillin, Aciclovir/Acyclovir ...) and dropping salt words
   (hydrochloride, sodium, maleate ...).
2. **Strengths** - identical list of strengths after unit conversion (500 mcg == 0.5 mg).
3. **Dosage form** - tablet / capsule / injection / oral liquid / cream ... must agree, and so must
   the release type (plain, modified-release SR/ER/XL, dispersible, chewable, sublingual).
4. **Pack size** - brands are priced *per unit* (per tablet, per ml, per gram) so a strip of 15
   is never compared with a Jan Aushadhi pack of 10.

``market_avg_price`` is the *median* brand price per unit scaled to the Jan Aushadhi pack size, so
``jan_price`` and ``market_avg_price`` always describe the same quantity of medicine.

The output has the same schema as the database produced by the original embedding pipeline
(``scripts/legacy``), plus ``matched_brand_count``. Unlike that pipeline it needs no GPU, is deterministic,
and does not discard brands that are cheaper than the generic.
"""

from __future__ import annotations

import csv
import difflib
import itertools
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

from . import data_cleaning

DEFAULT_MAX_BRANDS = 20
# Brand packs are only compared with the Jan Aushadhi pack when within this factor of its size:
# price does not scale linearly from a 5 ml ampoule to a 500 ml bag.
MAX_PACK_RATIO = 4.0

# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #
# Salt / counter-ion words that do not change the active ingredient for matching purposes.
SALT_WORDS = frozenset("""
    hydrochloride hcl hydrobromide sodium potassium calcium magnesium maleate besylate besilate
    tartrate succinate sulphate sulfate phosphate mesylate mesilate acetate citrate fumarate
    bromide nitrate dihydrate trihydrate monohydrate hemihydrate anhydrous proxetil axetil
    medoxomil pivoxil dipropionate valerate propionate furoate palmitate stearate disodium
    trisodium acid
""".split())

# Words that describe the dosage form, pack or pharmacopoeia, not the active ingredient.
STOP_WORDS = frozenset("""
    s tablet tablets tab capsule capsules cap injection injections infusion syrup suspension solution
    oral drops drop eye ear nasal cream ointment gel lotion powder dispersible chewable sublingual
    release prolonged extended sustained modified controlled delayed slow gastro resistant enteric
    coated film soft gelatin hard rapid orally disintegrating sterile vial vials ampoule pack dry
    co trimoxazole cotrimoxazole and with per for of in the mg mcg ug g gm ml iu million w v ip bp usp
    ph eur janaushadhi forte plus water wfi pre filled prefilled syringe mdi inhaler spray paediatric
    pediatric intravenous intramuscular subcutaneous flavoured wash mouthwash shampoo gum chewing soap
""".split())

# Spelling variants -> one canonical spelling.
SYNONYMS = {
    "aciclovir": "acyclovir", "amoxycillin": "amoxicillin", "sulphamethoxazole": "sulfamethoxazole",
    "sulphasalazine": "sulfasalazine", "sulphadiazine": "sulfadiazine", "clavulanate": "clavulanic",
    "lignocaine": "lidocaine", "frusemide": "furosemide", "albuterol": "salbutamol",
    "epinephrine": "adrenaline", "meperidine": "pethidine", "rifampin": "rifampicin",
    "ciclosporin": "cyclosporine", "cefalexin": "cephalexin", "cefradine": "cephradine",
    "acetaminophen": "paracetamol", "glyburide": "glibenclamide", "thiamin": "thiamine",
    "mecobalamin": "methylcobalamin", "cetrizine": "cetirizine", "tazobactum": "tazobactam",
}
PHRASES = {"vitamin d3": "cholecalciferol", "vitamin d 3": "cholecalciferol"}

_TOKEN_RE = re.compile(r"[a-z][a-z0-9]*")
_STEREO_PREFIX_RE = re.compile(r"\b(levo|dextro|dl|l|d)-(?=[a-z])")
_DENOMINATOR_RE = re.compile(r"(?:/|\bper(?=\s|\d))\s*\d*\.?\d*\s*(?:ml|gm|g)\b", re.IGNORECASE)
# "(2mg per ml)" / "(6mg/ml)" is the concentration of the solution, not a second ingredient.
_CONCENTRATION_RE = re.compile(
    r"\(\s*\d+(?:\.\d+)?\s*(?:mg|mcg|g|iu)\s*(?:/|per)\s*\d*\.?\d*\s*ml\s*\)", re.IGNORECASE
)
_STRENGTH_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:(million\s*iu|iu|mcg|µg|ug|mg|gm|g)(?![a-z])|(%))", re.IGNORECASE
)

# Dosage-form families, checked in order (so "powder for injection" is an injection).
_FAMILIES: Sequence[Tuple[str, "re.Pattern[str]"]] = [
    (name, re.compile(pattern))
    for name, pattern in [
        ("eye", r"\beye\b|ophthalmic"),
        ("ear", r"\bear\b|otic"),
        ("nasal", r"nasal"),
        ("inhalation", r"inhal|rotacap|respule|\bmdi\b|nebuli"),
        ("injection", r"inject|infusion|\binj\b"),
        ("tablet", r"tablet|\btab\b|caplet"),
        ("capsule", r"capsule|\bcap\b"),
        ("oral_liquid", r"syrup|suspension|oral solution|oral drops|expectorant|elixir|liquid|\bsolution\b|\bdrops?\b|emulsion"),
        ("cream", r"\bcream\b"),
        ("ointment", r"ointment"),
        ("gel", r"\bgel\b"),
        ("lotion", r"lotion"),
        ("powder", r"powder|sachet|granule"),
        ("wash", r"mouth ?wash|gargle|\bwash\b"),
        ("shampoo", r"shampoo"),
        ("spray", r"\bspray\b"),
        ("gum", r"\bgum\b"),
    ]
]

# Release types. Enteric/gastro-resistant is treated as "plain" because many catalogue entries
# do not label the coating, so requiring it would discard valid matches.
_RELEASES: Sequence[Tuple[str, "re.Pattern[str]"]] = [
    (name, re.compile(pattern))
    for name, pattern in [
        ("modified", r"prolonged|extended|sustained|modified|controlled|slow release|retard|\b(?:sr|er|xl|cr|xr|mr|pr|la)\b"),
        ("dispersible", r"dispersible|disintegrat|dissolving|melt|\b(?:dt|md)\b"),
        ("chewable", r"chewable|\bchew"),
        ("sublingual", r"sublingual|\bsl\b"),
    ]
]


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def ingredient_words(text: str, spelling: Optional[Dict[str, str]] = None) -> FrozenSet[str]:
    """Canonical set of active-ingredient words in ``text`` (generic name or salt composition).

    ``spelling`` optionally maps misspelt words to the catalogue's spelling (see
    :func:`build_spelling_map`).
    """
    lowered = _STEREO_PREFIX_RE.sub(r"\1", text.lower())  # "Levo-carnitine" == "Levocarnitine"
    for phrase, replacement in PHRASES.items():
        lowered = lowered.replace(phrase, replacement)
    spelling = spelling or {}
    tokens = [spelling.get(t, t) for t in (SYNONYMS.get(t, t) for t in _TOKEN_RE.findall(lowered))]
    core = [t for t in tokens if t not in STOP_WORDS]
    stems = [t for t in core if t not in SALT_WORDS]
    return frozenset(stems or core)  # "Sodium Chloride" would otherwise become empty


_AFTER_AMOUNT_RE = re.compile(r"\d\s*(?:mg|mcg|µg|ug|gm|g|iu|%)\s*$", re.IGNORECASE)


def _strip_concentrations(text: str) -> str:
    """Drop "(2mg per ml)" when it directly follows an amount ("50mg (2mg per ml)").

    In a salt composition such as "Amoxicillin (400mg/5ml)" the parenthesis *is* the strength and
    follows an ingredient name, so it is kept.
    """
    def repl(match: "re.Match[str]") -> str:
        return " " if _AFTER_AMOUNT_RE.search(text[: match.start()]) else match.group(0)

    return _CONCENTRATION_RE.sub(repl, text)


def strengths(text: str) -> Tuple[Tuple[str, float], ...]:
    """Sorted, unit-normalised strengths: mass in mg, plus IU and % kept as their own classes."""
    cleaned = _DENOMINATOR_RE.sub(" ", _strip_concentrations(text))
    found: List[Tuple[str, float]] = []
    for number, unit, percent in _STRENGTH_RE.findall(cleaned):
        value, unit = float(number), re.sub(r"\s+", " ", (unit or percent).lower())
        if unit in ("mg",):
            found.append(("mg", round(value, 4)))
        elif unit in ("mcg", "µg", "ug"):
            found.append(("mg", round(value / 1000, 4)))
        elif unit in ("g", "gm"):
            found.append(("mg", round(value * 1000, 4)))
        elif unit == "iu":
            found.append(("iu", round(value, 4)))
        elif unit.startswith("million"):
            found.append(("iu", round(value * 1_000_000, 4)))
        else:  # %
            found.append(("%", round(value, 4)))
    return tuple(sorted(found))


def dosage_form(text: str) -> Optional[str]:
    lowered = text.lower()
    for name, pattern in _FAMILIES:
        if pattern.search(lowered):
            return name
    return None


def release_type(text: str) -> str:
    lowered = text.lower()
    for name, pattern in _RELEASES:
        if pattern.search(lowered):
            return name
    return "plain"


def parse_jan_pack(unit_size: str) -> Optional[Tuple[str, float]]:
    """Jan Aushadhi pack -> (kind, amount), e.g. "10's" -> ("count", 10), "100 ml" -> ("ml", 100)."""
    text = unit_size.strip().lower()
    m = re.match(r"(\d+)\s*'?s\b", text)
    if m:
        return "count", float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*ml\b", text)
    if m:
        return "ml", float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:gm|g)\b", text)
    if m:
        return "g", float(m.group(1))
    if re.search(r"\b(vial|ampoule|ampule|cartridge|one in mono)", text):
        return "count", 1.0
    return None


_CONTAINER_RE = re.compile(
    r"^(?P<container>[a-z ]+?)\s+of\s+(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>ml|gm|g)?\b", re.IGNORECASE
)
_SINGLE_UNIT_CONTAINERS = ("vial", "ampoule", "ampule", "cartridge", "prefilled")


def parse_brand_pack(quantity: str) -> Dict[str, float]:
    """Brand pack text -> every comparable amount it contains.

    "strip of 10 tablets" -> {"count": 10};  "bottle of 60 ml Syrup" -> {"ml": 60};
    "vial of 10 ml Injection" -> {"count": 1, "ml": 10} (one vial holding 10 ml).
    """
    m = _CONTAINER_RE.match(quantity.strip())
    if not m:
        return {}
    container, number, unit = m.group("container").lower(), float(m.group("num")), (m.group("unit") or "").lower()
    amounts: Dict[str, float] = {}
    if unit == "ml":
        amounts["ml"] = number
    elif unit in ("gm", "g"):
        amounts["g"] = number
    else:
        amounts["count"] = number
    if unit and container.split()[0] in _SINGLE_UNIT_CONTAINERS:
        amounts["count"] = 1.0
    return {k: v for k, v in amounts.items() if v > 0}


def _is_modified_name(name: str) -> bool:
    return bool(re.search(r"\b(?:sr|er|xl|cr|xr|mr|pr)\b", name.lower()))


def _to_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


# --------------------------------------------------------------------------- #
# Brand catalogue index
# --------------------------------------------------------------------------- #
class BrandRow:
    __slots__ = ("name", "mrp", "strengths", "form", "release", "packs", "maker_size")

    def __init__(self, name: str, mrp: float, strength: Tuple[Tuple[str, float], ...], form: Optional[str],
                 release: str, packs: Dict[str, float], maker_size: int = 0):
        self.name, self.mrp, self.strengths, self.form, self.release, self.packs = (
            name, mrp, strength, form, release, packs)
        self.maker_size = maker_size  # products by the same manufacturer: a cheap popularity proxy


def index_brands(rows: Iterable[Dict[str, str]]) -> Dict[FrozenSet[str], List[BrandRow]]:
    """Group catalogue rows by their active-ingredient word set (one dict lookup per product)."""
    rows = list(rows)
    maker_sizes = Counter((r.get("Manufacturer") or "").strip().lower() for r in rows)
    index: Dict[FrozenSet[str], List[BrandRow]] = defaultdict(list)
    for row in rows:
        salt = (row.get("Salt_Composition") or "").strip()
        name = (row.get("Name") or "").strip()
        mrp = _to_float(row.get("MRP"))
        if not salt or not name or mrp is None:
            continue
        words = ingredient_words(salt)
        strength = strengths(salt)
        if not words:
            continue
        quantity = row.get("Quantity") or ""
        form = dosage_form(quantity) or dosage_form(name)
        release = release_type(quantity)
        if release == "plain" and _is_modified_name(name):
            release = "modified"
        packs = parse_brand_pack(quantity)
        maker = (row.get("Manufacturer") or "").strip().lower()
        index[words].append(BrandRow(name, mrp, strength, form, release, packs, maker_sizes[maker]))
    return index


def build_spelling_map(
    jan_names: Iterable[str], index: Dict[FrozenSet[str], List[BrandRow]], cutoff: float = 0.9
) -> Dict[str, str]:
    """Map Jan Aushadhi ingredient words missing from the catalogue to their nearest catalogue spelling.

    The catalogue contains typos ("Tazobactum"), so exact comparison would silently drop those
    products. Only words that do not occur in the catalogue at all are remapped, they must share
    their first letter and be at least 6 letters long, and the similarity cutoff is strict.
    """
    catalogue_vocab = set().union(*index.keys()) if index else set()
    by_letter: Dict[str, List[str]] = defaultdict(list)
    for word in catalogue_vocab:
        by_letter[word[0]].append(word)

    jan_vocab = set()
    for name in jan_names:
        jan_vocab |= ingredient_words(name)

    mapping: Dict[str, str] = {}
    for word in sorted(jan_vocab - catalogue_vocab):
        if len(word) < 6 or word.isdigit():
            continue
        close = difflib.get_close_matches(word, by_letter.get(word[0], []), n=1, cutoff=cutoff)
        if close:
            mapping[word] = close[0]
    return mapping


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #
def match_brands(
    generic_name: str,
    unit_size: str,
    index: Dict[FrozenSet[str], List[BrandRow]],
    spelling: Optional[Dict[str, str]] = None,
) -> List[Tuple[str, float, int]]:
    """Return [(brand name, price for one Jan Aushadhi pack, manufacturer size)] for one product."""
    words = ingredient_words(generic_name, spelling)
    wanted_strengths = strengths(generic_name)
    form = dosage_form(generic_name)
    if not words or form is None:
        return []
    release = release_type(generic_name)
    pack = parse_jan_pack(unit_size)

    def collect(keys: Iterable[FrozenSet[str]]) -> List[Tuple[str, float, int]]:
        matches: List[Tuple[str, float, int]] = []
        seen = set()
        for key in keys:
            for brand in index.get(key, ()):
                if brand.strengths != wanted_strengths or brand.form != form or brand.release != release:
                    continue
                if brand.name in seen:
                    continue
                if pack is None:
                    price = brand.mrp  # unknown Jan pack: fall back to the raw strip price
                else:
                    kind, amount = pack
                    if kind not in brand.packs:
                        continue  # cannot compare a pack measured in a different unit
                    ratio = brand.packs[kind] / amount
                    if not (1 / MAX_PACK_RATIO <= ratio <= MAX_PACK_RATIO):
                        continue  # pack too different in size for a fair price comparison
                    price = brand.mrp / brand.packs[kind] * amount
                seen.add(brand.name)
                matches.append((brand.name, price, brand.maker_size))
        return matches

    exact = collect([words])
    if exact or wanted_strengths == () or len(words) < 2:
        return exact

    # Fallback: the Jan name may carry a descriptive extra word ("Paediatric", "Liposomal").
    # Drop up to two words; the strength list must still match exactly, so a real ingredient
    # cannot be dropped silently (its strength would no longer line up).
    for drop in (1, 2):
        if len(words) - drop < 1:
            break
        found = collect(frozenset(c) for c in itertools.combinations(sorted(words), len(words) - drop))
        if found:
            return found
    return []


def build_records(
    jan_rows: Iterable[Dict[str, str]],
    brand_index: Dict[FrozenSet[str], List[BrandRow]],
    max_brands: int = DEFAULT_MAX_BRANDS,
) -> List[Dict[str, Any]]:
    """One record per Jan Aushadhi product, in the original file order."""
    jan_rows = list(jan_rows)
    spelling = build_spelling_map(
        (data_cleaning.fix_typos((r.get("Generic Name") or "")) for r in jan_rows), brand_index
    )
    records: List[Dict[str, Any]] = []
    for row in jan_rows:
        name = data_cleaning.fix_typos((row.get("Generic Name") or "").strip())
        unit_size = (row.get("Unit Size") or "").strip()
        jan_price = _to_float(row.get("MRP")) or 0.0

        record: Dict[str, Any] = {
            "generic_name": name,
            "jan_price": jan_price,
            "unit_size": unit_size,
            "common_brands": [],
            "found_match": False,
        }
        if not data_cleaning.is_device(name):
            matches = match_brands(name, unit_size, brand_index, spelling)
            if matches:
                prices = [price for _, price, _ in matches]
                median = statistics.median(prices)
                # Example brands: those from the largest manufacturers first (the ones people actually
                # search for), then closest to the median price. Deterministic.
                chosen = sorted(matches, key=lambda m: (-m[2], abs(m[1] - median), m[0]))[:max_brands]
                record["common_brands"] = [n for n, _, _ in chosen]
                record["found_match"] = True
                record["market_avg_price"] = round(median, 2)
                record["matched_brand_count"] = len(matches)
        records.append(data_cleaning.clean_record(record))
    return records


# --------------------------------------------------------------------------- #
# File-level entry points
# --------------------------------------------------------------------------- #
def read_csv_rows(path: str | Path) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def build_database(
    jan_csv: str | Path,
    brands_csv: str | Path,
    output: str | Path,
    max_brands: int = DEFAULT_MAX_BRANDS,
) -> Dict[str, Any]:
    """Read both CSVs, match, clean and write the JSON database. Returns summary statistics."""
    index = index_brands(read_csv_rows(brands_csv))
    records = build_records(read_csv_rows(jan_csv), index, max_brands=max_brands)
    data_cleaning.save_json(records, output)

    matched = [r for r in records if r["found_match"]]
    savings = Counter(r["savings_alert"].split(" ")[0] for r in records)
    return {
        "records": len(records),
        "matched": len(matched),
        "unmatched": len(records) - len(matched),
        "with_real_savings": savings.get("Save", 0),
        "price_unavailable": sum(1 for r in records if r["savings_alert"] == "Price Unavailable"),
        "output": str(output),
    }
