import unittest

from tests import _paths  # noqa: F401
from medperplexity.config import DEFAULT_DB_PATH
from medperplexity.generic_finder import GenericFinder, compute_savings, normalize

TINY_DB = [
    {"generic_name": "Atorvastatin Tablets IP 10mg", "jan_price": 8.25, "unit_size": "10's",
     "market_avg_price": 66.15, "common_brands": ["Atorlip 10 Tablet", "Atorin 10 Tablet"]},
    {"generic_name": "Metformin Hydrochloride Tablets IP 500mg", "jan_price": 5.0, "unit_size": "10's",
     "market_avg_price": 20.0, "common_brands": ["Glycomet 500 Tablet"]},
    {"generic_name": "Linagliptin 2.5mg and Metformin 500mg Tablets", "jan_price": 30.0, "unit_size": "10's",
     "market_avg_price": 120.0, "common_brands": ["Linares M Tablet"]},
    {"generic_name": "Pilocarpine Eye Drops IP 2% W/V", "jan_price": 0.0, "unit_size": "5ml",
     "common_brands": ["Pilocar Drops"]},
    {"generic_name": "Cheapo Tablets", "jan_price": 50.0, "unit_size": "10's",
     "market_avg_price": 40.0, "common_brands": ["Cheapo Brand Tablet"]},
]


class SavingsTests(unittest.TestCase):
    def test_savings(self):
        r = compute_savings(8.25, 66.15)
        self.assertEqual(r["price_status"], "savings")
        self.assertEqual(r["savings_amount"], 57.9)
        self.assertEqual(r["savings_percent"], 87.5)

    def test_zero_jan_price_is_unavailable_not_100_percent(self):
        self.assertEqual(compute_savings(0, 50)["price_status"], "price_unavailable")

    def test_missing_market_price(self):
        self.assertEqual(compute_savings(10, None)["price_status"], "price_unavailable")

    def test_no_savings(self):
        self.assertEqual(compute_savings(50, 40)["price_status"], "no_savings")


class TinyDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.finder = GenericFinder(TINY_DB)

    def test_brand_substring_match(self):
        r = self.finder.search("Atorlip 10")
        self.assertTrue(r["found"])
        self.assertEqual(r["match"]["generic_name"], "Atorvastatin Tablets IP 10mg")
        self.assertEqual(r["match"]["matched_on"], "brand")
        self.assertIn("Save", r["message"])

    def test_generic_name_match_is_case_and_space_insensitive(self):
        r = self.finder.search("  ATORVASTATIN   tablets ip 10mg ")
        self.assertTrue(r["found"])
        self.assertEqual(r["match"]["matched_on"], "generic")

    def test_single_ingredient_beats_combination(self):
        r = self.finder.search("metformin 500")
        self.assertEqual(r["match"]["generic_name"], "Metformin Hydrochloride Tablets IP 500mg")

    def test_typo_is_tolerated(self):
        r = self.finder.search("Atorvastatin Tablets IP 10 mg")
        self.assertTrue(r["found"])

    def test_short_query_does_not_substring_match(self):
        self.assertFalse(self.finder.search("met")["found"])

    def test_unknown_drug(self):
        r = self.finder.search("xyzzyqq")
        self.assertFalse(r["found"])
        self.assertIn("No direct Jan Aushadhi substitute", r["message"])

    def test_empty_query(self):
        self.assertFalse(self.finder.search("   ")["found"])

    def test_price_unavailable_is_reported(self):
        r = self.finder.search("Pilocarpine Eye Drops IP 2% W/V")
        self.assertTrue(r["found"])
        self.assertEqual(r["match"]["price_status"], "price_unavailable")
        self.assertIsNone(r["match"]["savings_amount"])

    def test_generic_costlier_than_brand(self):
        r = self.finder.search("Cheapo Brand Tablet")
        self.assertEqual(r["match"]["price_status"], "no_savings")
        self.assertIn("not cheaper", r["message"])

    def test_normalize(self):
        self.assertEqual(normalize("  Foo   BAR "), "foo bar")


@unittest.skipUnless(DEFAULT_DB_PATH.exists(), "bundled database missing")
class BundledDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.finder = GenericFinder.from_json()

    def test_every_sampled_stored_brand_finds_its_own_record(self):
        """Round trip: searching for a stored brand name must return that exact brand."""
        with_brands = [r for r in self.finder.records if r["common_brands"]]
        for rec in with_brands[:: max(1, len(with_brands) // 20)]:
            brand = rec["common_brands"][0]
            result = self.finder.search(brand)
            self.assertTrue(result["found"], brand)
            self.assertEqual(normalize(result["match"]["matched_text"]), normalize(brand))

    def test_famous_brands(self):
        r = self.finder.search("Dolo 650")
        self.assertTrue(r["found"])
        self.assertTrue(r["match"]["generic_name"].startswith("Paracetamol"))
        r = self.finder.search("Telma 40")
        self.assertTrue(r["match"]["generic_name"].startswith("Telmisartan"))

    def test_generic_name_lookup_reports_savings(self):
        r = self.finder.search("Atorvastatin Tablets IP 10mg")
        self.assertEqual(r["match"]["price_status"], "savings")
        self.assertGreater(r["match"]["savings_percent"], 0)

    def test_no_bogus_hundred_percent_savings(self):
        for rec in self.finder.records:
            self.assertNotIn("(100%)", rec["savings_alert"])

    def test_every_record_with_brands_is_marked_matched(self):
        for rec in self.finder.records:
            self.assertEqual(bool(rec["common_brands"]), rec["found_match"], rec["generic_name"])


class FuzzyGuardTests(unittest.TestCase):
    def test_shared_boilerplate_does_not_create_false_matches(self):
        db = [{"generic_name": "Nandrolone Decanoate Injection IP 25 mg per ml", "jan_price": 10.0,
               "unit_size": "1 ml", "market_avg_price": 50.0, "common_brands": ["Ndoate 25mg Injection"]}]
        self.assertFalse(GenericFinder(db).search("Ondace 2mg Injection")["found"])

    def test_hyphenated_product_is_not_a_prefix_match(self):
        db = [{"generic_name": "Aspirin and Atorvastatin Capsules", "jan_price": 10.0, "unit_size": "10's",
               "market_avg_price": 50.0, "common_brands": ["Atorlip-ASP 10 Capsule"]}]
        self.assertFalse(GenericFinder(db).search("Atorlip 10")["found"])


if __name__ == "__main__":
    unittest.main()
