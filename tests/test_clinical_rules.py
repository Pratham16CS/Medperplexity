import json
import os
import tempfile
import unittest
from pathlib import Path

from tests import _paths  # noqa: F401
from medperplexity.clinical_rules import (
    as_list,
    check_patient_flags,
    extract_known_drugs,
    flags_status,
    patient_conditions,
    worst_status,
)
from medperplexity.patients import PatientStore, patient_view
from medperplexity.config import PROJECT_ROOT

SAMPLE = PROJECT_ROOT / "data" / "patients.sample.json"


def types(flags):
    """Return flag type/severity pairs while preserving emitted order."""
    return [(f["type"], f["severity"]) for f in flags]


def flag_type_set(flags):
    return {flag["type"] for flag in flags}


class AllergyTests(unittest.TestCase):
    def patient(self, allergies, meds=()):
        return {"allergies": allergies, "current_medications": list(meds)}

    def test_class_allergy_blocks_members(self):
        self.assertEqual(
            types(check_patient_flags(self.patient(["Penicillin"]), ["Amoxicillin 500"])),
            [("allergy", "blocked")],
        )
        self.assertEqual(
            types(check_patient_flags(self.patient(["sulfa"]), ["Cotrimoxazole"])),
            [("allergy", "blocked")],
        )

    def test_same_drug_blocks(self):
        self.assertEqual(
            types(check_patient_flags(self.patient(["aspirin"]), ["Aspirin 75"])),
            [("allergy", "blocked")],
        )
        self.assertEqual(
            types(check_patient_flags(self.patient(["Diclofenac"]), ["diclofenac sodium 50"])),
            [("allergy", "blocked")],
        )

    def test_cross_reactivity_within_class_is_caution(self):
        self.assertEqual(
            types(check_patient_flags(self.patient(["aspirin"]), ["Diclofenac 50"])),
            [("allergy_cross_reactivity", "caution")],
        )

    def test_unrelated_drug_is_clean(self):
        self.assertEqual(
            check_patient_flags(self.patient(["penicillin"]), ["Paracetamol 650"]),
            [],
        )

    def test_nsaid_class_alias(self):
        self.assertEqual(
            types(check_patient_flags(self.patient(["NSAIDs"]), ["Ibuprofen"])),
            [("allergy", "blocked")],
        )

    def test_allergy_formats(self):
        self.assertEqual(as_list("penicillin, Sulfa; latex"), ["penicillin", "sulfa", "latex"])
        self.assertEqual(
            as_list([{"name": "Aspirin"}, {"drug": "Codeine"}]),
            ["aspirin", "codeine"],
        )
        self.assertEqual(as_list(["NKDA"]), [])
        self.assertEqual(as_list(None), [])

    def test_missing_allergy_record_is_flagged_as_info_only(self):
        flags = check_patient_flags({"current_medications": []}, ["Paracetamol"])
        self.assertEqual(types(flags), [("allergy_data_missing", "info")])
        self.assertEqual(flags_status(flags), "info")
        self.assertEqual(check_patient_flags({"allergies": []}, ["Paracetamol"]), [])

    def test_sulfonamide_allergy_does_not_block_amoxicillin(self):
        flags = check_patient_flags(
            {"allergies": ["sulfonamide antibiotic"], "current_medications": []},
            ["Amoxicillin 500 mg"],
        )
        self.assertNotIn("allergy", flag_type_set(flags))

    def test_penicillin_allergy_blocks_amoxicillin_and_status(self):
        flags = check_patient_flags(
            {"allergies": ["penicillin"], "current_medications": []},
            ["Amoxicillin 500 mg"],
        )
        self.assertIn("allergy", flag_type_set(flags))
        self.assertEqual(flags_status(flags), "blocked")


class DuplicateAndMiscTests(unittest.TestCase):
    def test_duplicate_therapy(self):
        flags = check_patient_flags(
            {"allergies": [], "medications": ["Telmisartan 40"]},
            ["Telma 40", "Telmisartan 80"],
        )
        self.assertEqual(types(flags), [("duplicate_therapy", "caution")])
        self.assertEqual(flags[0]["drug"], "Telmisartan 80")

    def test_duplicate_drug_detected_across_strengths(self):
        flags = check_patient_flags(
            {"allergies": [], "current_medications": ["Atorvastatin 20 mg"]},
            ["Atorvastatin 40 mg"],
        )
        self.assertIn("duplicate_therapy", flag_type_set(flags))

    def test_sodium_chloride_not_mistaken_for_potassium_chloride_duplicate(self):
        flags = check_patient_flags(
            {"allergies": [], "current_medications": ["Sodium chloride"]},
            ["Potassium chloride"],
        )
        self.assertNotIn("duplicate_therapy", flag_type_set(flags))

    def test_robust_to_bad_input(self):
        for patient in (None, {}, {"error": "x"}, "text", 5):
            self.assertEqual(check_patient_flags(patient, ["Aspirin"]), [])
        self.assertEqual(check_patient_flags({"allergies": ["penicillin"]}, []), [])

    def test_status_ordering(self):
        self.assertEqual(worst_status("approved", "caution"), "caution")
        self.assertEqual(worst_status("caution", "blocked", "info"), "blocked")
        self.assertEqual(worst_status("approved", "info"), "approved")
        self.assertEqual(worst_status("info", "approved"), "info")
        self.assertEqual(worst_status(), "info")
        self.assertEqual(worst_status("weird", "approved"), "weird")
        self.assertEqual(flags_status([]), "info")

    
    def test_extract_known_drugs(self):
        self.assertEqual(
            extract_known_drugs("Prescribe Amoxicillin 500 and Diclofenac for pain"),
            ["amoxicillin 500", "diclofenac"],
        )
        self.assertEqual(
            extract_known_drugs("start co-trimoxazole, then cotrimoxazole again"),
            ["co-trimoxazole", "cotrimoxazole"],
        )
        self.assertEqual(extract_known_drugs("patient has a headache"), [])
        self.assertEqual(extract_known_drugs(None), [])


    def test_conditions(self):
        self.assertEqual(
            patient_conditions({"condition_tags": ["Hypertension", "T2DM"]}),
            ["hypertension", "t2dm"],
        )


class InteractionTests(unittest.TestCase):
    """Regression coverage for the intentionally limited interaction catalogue."""

    def flags(self, current_meds, requested_drugs):
        patient = {"allergies": [], "current_medications": current_meds}
        return check_patient_flags(patient, requested_drugs)

    def test_potassium_chloride_with_ramipril_is_caution(self):
        flags = self.flags(["Ramipril 5 mg"], ["Potassium chloride supplement"])
        self.assertIn("interaction_potassium_raas", flag_type_set(flags))
        self.assertEqual(flags_status(flags), "caution")

    def test_potassium_product_with_telmisartan_is_caution(self):
        flags = self.flags(["Telmisartan 40 mg"], ["Potassium chloride"])
        self.assertIn("interaction_potassium_raas", flag_type_set(flags))

    def test_potassium_product_with_lisinopril_is_caution(self):
        flags = self.flags(["Lisinopril 10 mg"], ["Potassium supplement"])
        self.assertIn("interaction_potassium_raas", flag_type_set(flags))

    def test_warfarin_with_ibuprofen_is_caution(self):
        flags = self.flags(["Warfarin"], ["Ibuprofen 400 mg"])
        self.assertIn("interaction_anticoagulant_nsaid", flag_type_set(flags))
        self.assertEqual(flags_status(flags), "caution")

    def test_apixaban_with_diclofenac_is_caution(self):
        flags = self.flags(["Apixaban"], ["Diclofenac 50 mg"])
        self.assertIn("interaction_anticoagulant_nsaid", flag_type_set(flags))

    def test_isotretinoin_with_doxycycline_is_caution(self):
        flags = self.flags(["Isotretinoin"], ["Doxycycline 100 mg"])
        self.assertIn("interaction_isotretinoin_tetracycline", flag_type_set(flags))

    def test_clarithromycin_with_simvastatin_is_caution(self):
        flags = self.flags(["Simvastatin 20 mg"], ["Clarithromycin"])
        self.assertIn("interaction_macrolide_statin", flag_type_set(flags))

    def test_interaction_is_checked_within_a_single_order(self):
        flags = check_patient_flags(
            {"allergies": [], "current_medications": []},
            ["Potassium chloride", "Ramipril 5 mg"],
        )
        self.assertIn("interaction_potassium_raas", flag_type_set(flags))

    def test_unrelated_medications_do_not_trigger_known_interactions(self):
        flags = self.flags(["Metformin 500 mg"], ["Paracetamol 500 mg"])
        self.assertNotIn("interaction_potassium_raas", flag_type_set(flags))
        self.assertNotIn("interaction_anticoagulant_nsaid", flag_type_set(flags))
        self.assertNotIn("interaction_isotretinoin_tetracycline", flag_type_set(flags))
        self.assertNotIn("interaction_macrolide_statin", flag_type_set(flags))

    def test_rule_based_planner_extracts_potassium_chloride(self):
        drugs = extract_known_drugs("Prescribe Potassium chloride supplement")
        self.assertIn("potassium chloride", [drug.lower() for drug in drugs])

    def test_rule_based_planner_extracts_ramipril_with_strength(self):
        drugs = extract_known_drugs("Prescribe Ramipril 5 mg")
        self.assertIn("ramipril 5", [drug.lower() for drug in drugs])

    def test_rule_based_planner_extracts_multiple_interaction_drugs(self):
        drugs = extract_known_drugs(
            "Patient takes warfarin; prescribe ibuprofen 400 mg"
        )
        lowered = [drug.lower() for drug in drugs]
        self.assertIn("warfarin", lowered)
        self.assertIn("ibuprofen 400", lowered)


class PatientStoreTests(unittest.TestCase):
    def test_sample_file(self):
        store = PatientStore(SAMPLE)
        self.assertEqual(store.get("PAT-001")["age"], 58)
        self.assertIsNone(store.get("PAT-999"))
        self.assertEqual(store.error, "")

    def test_missing_and_corrupt_files(self):
        store = PatientStore("/nonexistent/patients.json")
        self.assertIsNone(store.get("x"))
        self.assertIn("not found", store.error)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.json"
            path.write_text("{broken", encoding="utf-8")
            bad = PatientStore(path)
            self.assertIsNone(bad.get("x"))
            self.assertIn("unreadable", bad.error)

    def test_list_format_and_reload_on_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.json"
            path.write_text(
                json.dumps([{"patient_id": "A", "age": 1}]),
                encoding="utf-8",
            )
            store = PatientStore(path)
            self.assertEqual(store.get("A")["age"], 1)

            path.write_text(
                json.dumps([{"patient_id": "A", "age": 2}]),
                encoding="utf-8",
            )
            os.utime(
                path,
                (path.stat().st_atime + 5, path.stat().st_mtime + 5),
            )
            self.assertEqual(store.get("A")["age"], 2)

    def test_get_returns_a_copy(self):
        store = PatientStore(SAMPLE)
        store.get("PAT-001")["age"] = 999
        self.assertEqual(store.get("PAT-001")["age"], 58)

    def test_patient_view_removes_identifiers(self):
        view = patient_view(
            {
                "name": "X",
                "patient_id": "1",
                "phone": "9",
                "email": "e",
                "age": 5,
                "allergies": ["a"],
                "notes": "n" * 1000,
            }
        )
        self.assertEqual(set(view), {"age", "allergies", "notes"})
        self.assertEqual(len(view["notes"]), 400)


if __name__ == "__main__":
    unittest.main()
