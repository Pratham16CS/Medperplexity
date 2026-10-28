"""Comprehensive test suite for the MedPerplexity Patient Record Summary Workflow."""

import unittest
from typing import Any, Dict, List, Optional
from tests import _paths  # noqa: F401
from medperplexity.agent import AgentDeps, MedAgent, _fallback_plan, _is_record_summary_request
from medperplexity.llm import LLMUnavailable
from medperplexity.patients import PatientStore


class ScriptedPlannerLLM:
    """Mock LLM for testing planner responses."""

    def __init__(self, plan_output: Optional[Dict[str, Any]] = None, fail: bool = False):
        self.plan_output = plan_output or {}
        self.fail = fail

    def complete_json(self, system: str, user: str, validator: Any, max_tokens: int = 400):
        if self.fail:
            raise LLMUnavailable("Simulated LLM network timeout", attempts=[{"provider": "test", "error": "timeout"}])
        return validator(self.plan_output), _FakeAudit()


class _FakeAudit:
    def audit(self):
        return {"provider": "mock-llm", "latency_ms": 12, "cached": False}


class TestRecordSummaryWorkflow(unittest.TestCase):
    def setUp(self):
        self.agent = MedAgent()

    # -------------------------------------------------------------------------
    # Test A: Primary Query Routing & Grounded Output Verification
    # -------------------------------------------------------------------------
    def test_a_exact_query_record_summary_pat_001(self):
        query = (
            "Summarize this patient's recorded medical conditions, allergies, and "
            "current medications using only the patient record. Clearly distinguish "
            "documented facts from missing information. Do not invent any details."
        )
        res = self.agent.ask("PAT-001", query, thread_id="test-a-pat001")

        self.assertEqual(res["status"], "info")
        self.assertEqual(res["title"], "Patient Record Summary")
        self.assertEqual(res["evidence_level"], "not_applicable")
        self.assertEqual(res["claim_support"]["status"], "not_assessed")

        # Verify audit properties
        audit = res.get("audit") or {}
        plan = audit.get("plan") or {}
        tools = audit.get("tools") or {}
        self.assertEqual(plan.get("task"), "record_summary")
        self.assertEqual(plan.get("drugs"), [])
        self.assertIsNone(tools.get("evidence"))
        self.assertIsNone(tools.get("substitute"))
        self.assertEqual(tools.get("patient_record"), "retrieved")

        # Verify no tool error/invalid_input
        self.assertNotEqual(tools.get("evidence"), "invalid_input")
        self.assertNotIn("invalid_input", str(audit))

        # Verify documented patient facts
        rec = res.get("record_summary") or {}
        self.assertIn("osteoarthritis", rec.get("conditions", []))
        self.assertIn("hypertension", rec.get("conditions", []))
        self.assertIn("type 2 diabetes", rec.get("conditions", []))
        self.assertIn("penicillin", rec.get("allergies", []))
        self.assertIn("aspirin", rec.get("allergies", []))
        self.assertIn("Metformin 500", rec.get("current_medications", []))
        self.assertIn("Telmisartan 40", rec.get("current_medications", []))

        # Verify explicit missing information
        msg = res.get("message", "")
        self.assertIn("Missing / Unspecified Information in Record", msg)
        self.assertIn("dosing schedule", msg.lower())
        self.assertIn("vital signs", msg.lower())

    # -------------------------------------------------------------------------
    # Test B: Grounding & Empty Allergy Field Handling
    # -------------------------------------------------------------------------
    def test_b_grounding_empty_allergies_pat_002(self):
        query = "Summarize this patient's recorded medical conditions, allergies, and current medications."
        res = self.agent.ask("PAT-002", query, thread_id="test-b-pat002")

        self.assertEqual(res["status"], "info")
        self.assertEqual(res["title"], "Patient Record Summary")

        msg = res.get("message", "")
        # Must NOT claim "no allergies"
        self.assertNotIn("no allergies", msg.lower())
        self.assertNotIn("no known allergies", msg.lower())
        self.assertIn("not documented in record", msg.lower())

        # Verify conditions and medications
        rec = res.get("record_summary") or {}
        self.assertEqual(rec.get("conditions"), ["migraine"])
        self.assertEqual(rec.get("current_medications"), ["Paracetamol 500"])
        self.assertFalse(rec.get("allergies_documented"))

    # -------------------------------------------------------------------------
    # Test C: Missing Patient / Invalid ID Handling
    # -------------------------------------------------------------------------
    def test_c_missing_patient(self):
        query = "Summarize this patient's recorded medical conditions"
        res = self.agent.ask("PAT-NONEXISTENT", query, thread_id="test-c-nonexistent")

        self.assertEqual(res["status"], "caution")
        self.assertEqual(res["title"], "Patient not found")
        self.assertIn("PAT-NONEXISTENT", res["message"])

    # -------------------------------------------------------------------------
    # Test D: Rule-based Fallback Planner Routing
    # -------------------------------------------------------------------------
    def test_d_rule_based_fallback_planning(self):
        patient = PatientStore().get("PAT-001")
        query = "Provide a summary of the patient chart and recorded history."
        plan = _fallback_plan(query, patient)

        self.assertEqual(plan.get("task"), "record_summary")
        self.assertEqual(plan.get("drugs"), [])
        self.assertIsNone(plan.get("clarification"))

    # -------------------------------------------------------------------------
    # Test E: Safety Regression - Allergy Check Uncompromised
    # -------------------------------------------------------------------------
    def test_e_allergy_safety_check_retained(self):
        query = "Can I prescribe Amoxicillin 500mg TDS for this patient?"
        self.assertFalse(_is_record_summary_request(query))

        res = self.agent.ask("PAT-001", query, thread_id="test-e-allergy")
        self.assertEqual(res["status"], "blocked")
        self.assertEqual(res["title"], "Blocked: allergy")
        self.assertTrue(any("penicillin" in f["detail"].lower() for f in res.get("flags", [])))

    # -------------------------------------------------------------------------
    # Test F: Safety Regression - Drug Interaction Check Uncompromised
    # -------------------------------------------------------------------------
    def test_f_interaction_safety_check_retained(self):
        query = "Prescribe Potassium chloride supplement for PAT-001"
        self.assertFalse(_is_record_summary_request(query))

        res = self.agent.ask("PAT-001", query, thread_id="test-f-interaction")
        self.assertIn(res["status"], ("caution", "blocked"))
        self.assertTrue(any("potassium" in f["detail"].lower() for f in res.get("flags", [])))

    # -------------------------------------------------------------------------
    # Test G: Generic Substitution & Literature Retrieval Distinction
    # -------------------------------------------------------------------------
    def test_g_generic_and_research_queries_not_misclassified(self):
        generic_q = "Find Jan Aushadhi generic alternatives for Metformin 500mg"
        self.assertFalse(_is_record_summary_request(generic_q))

        research_q = "Retrieve recent clinical guidelines for hypertension"
        self.assertFalse(_is_record_summary_request(research_q))


if __name__ == "__main__":
    unittest.main()
