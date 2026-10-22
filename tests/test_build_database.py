import csv
import json
import tempfile
import unittest
from pathlib import Path

from tests import _paths  # noqa: F401
from medperplexity import build_database as bd
from medperplexity.cli import main

JAN_HEADER = ["Sr No", "Drug Code", "Generic Name", "Unit Size", "MRP", "Group Name"]
JAN_ROWS = [
    ("Paracetamol Tablets IP 500 mg", "10's", "5.0"),
    ("Metformin Hydrochloride Tablets IP 500mg (Sustained Release)", "10's", "12"),
    ("Amoxycillin 500mg and Potassium Clavulanate 100mg Injection IP", "Vial", "37.5"),
    ("Cotton Wool IP 100 g", "1's", "10"),
    ("Pilocarpine Eye Drops IP 2% W/V", "5 ml", "0"),
    ("Unknownium Tablets 10mg", "10's", "9"),
    ("Losartan Potassium 50mg and Hydrochlorothiazide 12.5mg Tabelts IP", "10's", "8"),
    ("Pantoprazole Tablets IP 40mg", "10's", "4"),
]
BRAND_HEADER = ["Index", "Name", "MRP", "Quantity", "Manufacturer", "Salt_Composition", "Image_URL"]
BRAND_ROWS = [
    # Paracetamol 500 tablets: three real matches...
    ("Crocin 500 Tablet", "30", "strip of 15 tablets", "GSK", "Paracetamol (500mg)"),          # 2.0 each -> 20 per 10
    ("Dolo 500 Tablet", "20", "strip of 10 tablets", "Micro", "Paracetamol (500mg)"),          # 20
    ("Calpol 500 Tablet", "25", "strip of 10 tablets", "GSK", "Paracetamol (500mg)"),          # 25
    # ...and four that must be rejected
    ("Para 650 Tablet", "30", "strip of 10 tablets", "Other", "Paracetamol (650mg)"),           # strength
    ("Para Syrup", "40", "bottle of 60 ml syrup", "Other", "Paracetamol (500mg)"),             # dosage form
    ("Bulk Para 500", "150", "bottle of 100 tablets", "Other", "Paracetamol (500mg)"),         # pack 10x larger
    ("Combo Para", "30", "strip of 10 tablets", "Other", "Paracetamol (500mg) + Caffeine (50mg)"),  # extra ingredient
    # Metformin: only the sustained-release brand matches a sustained-release generic
    ("Glycomet SR 500 Tablet", "60", "strip of 10 tablet sr", "USV", "Metformin (500mg)"),
    ("Glycomet 500 Tablet", "30", "strip of 10 tablets", "USV", "Metformin (500mg)"),
    # Spelling variants Amoxycillin / Clavulanic Acid
    ("Amoxyclav 600 Injection", "100", "vial of 1 injection", "Alkem", "Amoxicillin  (500mg) +  Clavulanic Acid (100mg)"),
    ("Pilo 2% Eye Drop", "90", "bottle of 5 ml eye drop", "Ajanta", "Pilocarpine (2% w/v)"),
    ("Losar H Tablet", "50", "strip of 10 tablets", "Alkem", "Losartan Potassium (50mg) + Hydrochlorothiazide (12.5mg)"),
    # Catalogue typo ("Pantaprazole") that the spelling repair must bridge
    ("Pantocid 40 Tablet", "60", "strip of 10 tablets", "Sun", "Pantaprazole (40mg)"),
]


def write_csvs(tmp: Path):
    jan, brands = tmp / "jan.csv", tmp / "brands.csv"
    with open(jan, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(JAN_HEADER)
        for i, (name, unit, mrp) in enumerate(JAN_ROWS, 1):
            w.writerow([i, i, name, unit, mrp, "Group"])
    with open(brands, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(BRAND_HEADER)
        for i, (name, mrp, qty, maker, salt) in enumerate(BRAND_ROWS):
            w.writerow([i, name, mrp, qty, maker, salt, "http://x/img.jpg"])
    return jan, brands


class ParsingTests(unittest.TestCase):
    def test_ingredient_words_ignore_salts_forms_and_spelling(self):
        generic = bd.ingredient_words("Amoxycillin 500mg and Potassium Clavulanate 100mg Injection IP")
        salt = bd.ingredient_words("Amoxicillin  (500mg) +  Clavulanic Acid (100mg)")
        self.assertEqual(generic, salt)
        self.assertEqual(bd.ingredient_words("Metformin Hydrochloride Tablets"), frozenset({"metformin"}))
        self.assertEqual(bd.ingredient_words("Levo-carnitine"), bd.ingredient_words("Levocarnitine"))
        self.assertTrue(bd.ingredient_words("Sodium Chloride Injection"))  # never empty

    def test_strengths_are_normalised(self):
        self.assertEqual(bd.strengths("Atorvastatin 10 mg"), (("mg", 10.0),))
        self.assertEqual(bd.strengths("Vitamin 500mcg"), bd.strengths("0.5 mg"))
        self.assertEqual(bd.strengths("Ceftriaxone 1g and Tazobactam 125mg"), (("mg", 125.0), ("mg", 1000.0)))
        self.assertEqual(bd.strengths("Gel 1.16%w/w"), (("%", 1.16),))          # '%' glued to next word
        self.assertEqual(bd.strengths("Insulin 40 IU per ml"), (("iu", 40.0),))
        self.assertEqual(bd.strengths("Cisplatin 10 mg per10ml"), (("mg", 10.0),))
        self.assertEqual(bd.strengths("Paclitaxel 100mg (6mg/ml)"), (("mg", 100.0),))  # concentration, not ingredient
        self.assertEqual(bd.strengths("Amoxicillin (400mg/5ml)"), (("mg", 400.0),))
        self.assertEqual(bd.strengths("Amoxycillin (400mg/5ml) + Clavulanic Acid (57mg/5ml)"),
                         (("mg", 57.0), ("mg", 400.0)))  # both ingredients keep their strength
        self.assertEqual(bd.strengths("Colistin 1 Million IU"), (("iu", 1_000_000.0),))

    def test_forms_and_release(self):
        self.assertEqual(bd.dosage_form("Powder for Injection"), "injection")
        self.assertEqual(bd.dosage_form("strip of 10 soft gelatin capsules"), "capsule")
        self.assertEqual(bd.dosage_form("bottle of 5 ml eye drop"), "eye")
        self.assertEqual(bd.dosage_form("bottle of 60 ml Oral Suspension"), "oral_liquid")
        self.assertIsNone(bd.dosage_form("Surgical thing"))
        self.assertEqual(bd.release_type("Metformin Prolonged Release Tablets"), "modified")
        self.assertEqual(bd.release_type("strip of 10 tablet sr"), "modified")
        self.assertEqual(bd.release_type("strip of 10 tablet dt"), "dispersible")
        self.assertEqual(bd.release_type("strip of 10 tablets"), "plain")

    def test_packs(self):
        self.assertEqual(bd.parse_jan_pack("10's"), ("count", 10.0))
        self.assertEqual(bd.parse_jan_pack("100 ML"), ("ml", 100.0))
        self.assertEqual(bd.parse_jan_pack("15 gm tubes"), ("g", 15.0))
        self.assertEqual(bd.parse_jan_pack("Vial & Wfi"), ("count", 1.0))
        self.assertIsNone(bd.parse_jan_pack("Pair in Mono-Pack"))
        self.assertEqual(bd.parse_brand_pack("strip of 15 tablets"), {"count": 15.0})
        self.assertEqual(bd.parse_brand_pack("bottle of 60 ml Syrup"), {"ml": 60.0})
        self.assertEqual(bd.parse_brand_pack("vial of 10 ml Injection"), {"ml": 10.0, "count": 1.0})
        self.assertEqual(bd.parse_brand_pack("tube of 20 gm Cream"), {"g": 20.0})
        self.assertEqual(bd.parse_brand_pack("nonsense"), {})


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        jan, brands = write_csvs(tmp)
        cls.out = tmp / "out" / "medicines.json"
        cls.summary = bd.build_database(jan, brands, cls.out)
        cls.records = {r["generic_name"]: r for r in json.loads(cls.out.read_text(encoding="utf-8"))}
        cls.jan, cls.brands, cls.tmp = jan, brands, tmp

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_summary_and_order(self):
        self.assertEqual(self.summary["records"], len(JAN_ROWS))
        self.assertEqual(self.summary["matched"], 6)
        names = [r["generic_name"] for r in json.loads(self.out.read_text(encoding="utf-8"))]
        self.assertEqual(names[0], "Paracetamol Tablets IP 500 mg")  # Jan file order preserved

    def test_schema_matches_shipped_database(self):
        rec = self.records["Paracetamol Tablets IP 500 mg"]
        for key in ("generic_name", "jan_price", "unit_size", "common_brands", "found_match",
                    "market_avg_price", "savings_alert", "savings_percentage"):
            self.assertIn(key, rec)

    def test_exact_matching_rules(self):
        rec = self.records["Paracetamol Tablets IP 500 mg"]
        self.assertTrue(rec["found_match"])
        # 650mg, syrup, 10x-larger pack and extra-ingredient products are all rejected
        self.assertEqual(rec["matched_brand_count"], 3)
        self.assertEqual(set(rec["common_brands"]), {"Crocin 500 Tablet", "Dolo 500 Tablet", "Calpol 500 Tablet"})

    def test_prices_are_per_unit_normalised(self):
        rec = self.records["Paracetamol Tablets IP 500 mg"]
        # Crocin strip of 15 at 30 = 2.0 per tablet -> 20 per Jan pack of 10; median of [20, 20, 25] = 20
        self.assertEqual(rec["market_avg_price"], 20.0)
        self.assertEqual(rec["savings_alert"], "Save ₹15 (75%)")

    def test_example_brands_prefer_big_manufacturers_then_median_price(self):
        rec = self.records["Paracetamol Tablets IP 500 mg"]
        self.assertEqual(rec["common_brands"][:2], ["Crocin 500 Tablet", "Calpol 500 Tablet"])  # GSK has 2 products

    def test_release_type_must_match(self):
        rec = self.records["Metformin Hydrochloride Tablets IP 500mg (Sustained Release)"]
        self.assertEqual(rec["common_brands"], ["Glycomet SR 500 Tablet"])

    def test_spelling_variants_and_salts(self):
        self.assertEqual(self.records["Amoxycillin 500mg and Potassium Clavulanate 100mg Injection IP"]["common_brands"],
                         ["Amoxyclav 600 Injection"])

    def test_catalogue_typo_is_repaired(self):
        self.assertEqual(self.records["Pantoprazole Tablets IP 40mg"]["common_brands"], ["Pantocid 40 Tablet"])

    def test_jan_typo_fixed_and_matched(self):
        self.assertIn("Losartan Potassium 50mg and Hydrochlorothiazide 12.5mg Tablets IP", self.records)

    def test_zero_jan_price_is_unavailable(self):
        rec = self.records["Pilocarpine Eye Drops IP 2% W/V"]
        self.assertTrue(rec["found_match"])
        self.assertEqual(rec["savings_alert"], "Price Unavailable")

    def test_devices_and_unknowns_are_unmatched(self):
        for name in ("Cotton Wool IP 100 g", "Unknownium Tablets 10mg"):
            rec = self.records[name]
            self.assertFalse(rec["found_match"])
            self.assertEqual(rec["common_brands"], [])
            self.assertNotIn("market_avg_price", rec)

    def test_max_brands(self):
        out = self.tmp / "small.json"
        bd.build_database(self.jan, self.brands, out, max_brands=1)
        rec = {r["generic_name"]: r for r in json.loads(out.read_text(encoding="utf-8"))}["Paracetamol Tablets IP 500 mg"]
        self.assertEqual(len(rec["common_brands"]), 1)
        self.assertEqual(rec["matched_brand_count"], 3)

    def test_output_is_usable_by_the_finder(self):
        from medperplexity.generic_finder import GenericFinder

        result = GenericFinder.from_json(self.out).search("Dolo 500 Tablet")
        self.assertTrue(result["found"])
        self.assertEqual(result["match"]["generic_name"], "Paracetamol Tablets IP 500 mg")
        self.assertEqual(result["match"]["price_status"], "savings")

    def test_cli_build(self):
        out = self.tmp / "cli.json"
        self.assertEqual(main(["build", "--jan", str(self.jan), "--brands", str(self.brands), "-o", str(out)]), 0)
        self.assertTrue(out.is_file())
        self.assertEqual(main(["build", "--jan", str(self.jan), "--brands", str(self.tmp / "missing.csv")]), 2)


if __name__ == "__main__":
    unittest.main()
