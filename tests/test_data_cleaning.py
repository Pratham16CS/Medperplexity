import json
import tempfile
import unittest
from pathlib import Path

from tests import _paths  # noqa: F401
from medperplexity import data_cleaning as dc


class DeviceDetectionTests(unittest.TestCase):
    def test_real_devices(self):
        for name in ["Surgical Face Mask, Disposable", "Cotton Pads (Round)", "Reusable Menstrual Cup (Small)",
                     "Endotracheal Tube Cuffed, Size 4", "Maternity Sanitary Pads", "Glucometer Test Strip",
                     "Blood Transfusion Set with Filter 170 Micron", "Abdominal Belt Velcro, Cream color (Large)"]:
            self.assertTrue(dc.is_device(name), name)

    def test_medicines_are_not_devices(self):
        # Old substring matching wrongly flagged these ("Set" in OndanSETron, "Tape" in TAPEntadol, ...)
        for name in ["Ondansetron Tablets IP 4 mg", "Tapentadol 50mg Tablets", "Nicotine 2mg Oral Disintegrating Strips",
                     "Combikit of Eplerenone Tablets 25mg and Torsemide Tablets IP 10mg",
                     "Dinoprostone Gel 0.5 mg (Pre-filled syringe)", "Throat Spray (Pine Needle oil, Sage oil)",
                     "Metformin Tablets IP 500mg", "Paracetamol Tablets IP 500 mg"]:
            self.assertFalse(dc.is_device(name), name)


class TypoTests(unittest.TestCase):
    def test_fixes(self):
        self.assertEqual(dc.fix_typos("Cefepime 250 Mg Inection"), "Cefepime 250 Mg Injection")
        self.assertEqual(dc.fix_typos("Metformin Hydrchloride and Glimipride"), "Metformin Hydrochloride and Glimepiride")
        self.assertEqual(dc.fix_typos("Isosorbidemononitrate Tablets"), "Isosorbide Mononitrate Tablets")
        self.assertEqual(dc.fix_typos("Losartan 50mg Tabelts IP"), "Losartan 50mg Tablets IP")

    def test_correct_words_untouched(self):
        self.assertEqual(dc.fix_typos("Ketorolac Injection"), "Ketorolac Injection")
        self.assertEqual(dc.fix_typos("Vitamin B"), "Vitamin B")

    def test_non_string(self):
        self.assertIsNone(dc.fix_typos(None))


class PricingTests(unittest.TestCase):
    def test_zero_price(self):
        r = dc.recompute_pricing({"jan_price": 0.0, "market_avg_price": 50})
        self.assertEqual(r, {"savings_alert": "Price Unavailable", "savings_percentage": "N/A"})

    def test_savings(self):
        r = dc.recompute_pricing({"jan_price": 8.25, "market_avg_price": 66.15})
        self.assertEqual(r["savings_alert"], "Save ₹57 (87%)")
        self.assertEqual(r["savings_percentage"], "87%")

    def test_no_market_price(self):
        self.assertEqual(dc.recompute_pricing({"jan_price": 10})["savings_alert"], "N/A")

    def test_generic_costlier(self):
        self.assertEqual(dc.recompute_pricing({"jan_price": 50, "market_avg_price": 40})["savings_alert"], "No savings")


class RecordTests(unittest.TestCase):
    def test_clean_record_clears_device_brands_and_does_not_mutate_input(self):
        rec = {"generic_name": "Cotton Balls", "common_brands": ["Fake Brand"], "jan_price": 5.0}
        out = dc.clean_record(rec)
        self.assertEqual(out["common_brands"], [])
        self.assertEqual(rec["common_brands"], ["Fake Brand"])

    def test_clean_record_keeps_medicine_brands(self):
        rec = {"generic_name": "Ondansetron Tablets IP 4 mg", "common_brands": ["Ondazen 4mg Tablet"], "jan_price": 5.0,
               "market_avg_price": 30.0}
        self.assertEqual(dc.clean_record(rec)["common_brands"], ["Ondazen 4mg Tablet"])

    def test_merge_prefers_primary(self):
        primary = [{"generic_name": "A Tablets", "v": 1}]
        secondary = [{"generic_name": " a tablets ", "v": 2}, {"generic_name": "B Tablets", "v": 3}]
        merged = dc.merge_records(primary, secondary)
        self.assertEqual([r["v"] for r in merged], [1, 3])

    def test_build_clean_database_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "in.json", Path(tmp) / "out" / "db.json"
            src.write_text(json.dumps([{"generic_name": "Cefepime 250 Mg Inection", "common_brands": ["X"],
                                        "jan_price": 0.0}]), encoding="utf-8")
            summary = dc.build_clean_database(src, dst)
            self.assertEqual(summary["total_records"], 1)
            out = json.loads(dst.read_text(encoding="utf-8"))
            self.assertEqual(out[0]["generic_name"], "Cefepime 250 Mg Injection")
            self.assertEqual(out[0]["savings_alert"], "Price Unavailable")


if __name__ == "__main__":
    unittest.main()
