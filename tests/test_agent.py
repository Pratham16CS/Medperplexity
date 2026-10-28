import json
import sys
import threading
import tempfile
from pathlib import Path
import types
import unittest
from unittest import mock

from tests import _paths  # noqa: F401
from tests.fakes import FakeEntrez, make_article
from medperplexity import agent, agent_tools as at, pubmed
from medperplexity.agent import AgentDeps, MedAgent
from medperplexity.config import PROJECT_ROOT
from medperplexity.generic_finder import GenericFinder
from medperplexity.llm import LLMResult, LLMUnavailable
from medperplexity.patients import PatientStore
from medperplexity.session_store import SessionStore

SAMPLE = PROJECT_ROOT / "data" / "patients.sample.json"
DB = [
    {"generic_name": "Telmisartan Tablets IP 40mg", "jan_price": 5.0, "unit_size": "10's", "market_avg_price": 50.0,
     "common_brands": ["Telma 40 Tablet"]},
    {"generic_name": "Sumatriptan Tablets IP 50mg", "jan_price": 20.0, "unit_size": "4's", "market_avg_price": 120.0,
     "common_brands": ["Suminat 50 Tablet"]},
    {"generic_name": "Amoxycillin Capsules IP 500mg", "jan_price": 20.0, "unit_size": "10's", "market_avg_price": 90.0,
     "common_brands": ["Mox 500 Capsule"]},
]


# ----------------------------------------------------------------------------- test doubles
class ScriptedLLM:
    """Stands in for FallbackLLM: returns scripted objects, runs the real validators, records prompts."""

    def __init__(self, plan=None, explanation=None, plans=None, fail_plan=False, fail_safety=False):
        self.plans = list(plans) if plans else [plan or {"task": "prescription_check", "drugs": ["Sumatriptan 50"],
                                                          "intent": "safety"}]
        self.explanation = explanation or {"status": "approved", "title": "No conflict found",
                                           "message": "Evidence supports use.", "pmids": ["111"],
                                           "claim_checks": [{
                                               "claim": "This study evaluates sumatriptan treatment for acute migraine.",
                                               "pmid": "111", "verdict": "supported",
                                               "evidence_quote": "This study evaluates sumatriptan treatment for acute migraine.",
                                               "rationale": "Mock fixture: exact abstract statement."}]}
        self.fail_plan, self.fail_safety = fail_plan, fail_safety
        self.calls = []

    def complete_json(self, system, user, validator=None, **_kw):
        self.calls.append((system, user))
        is_plan = system.startswith("You are the planning step")
        if (is_plan and self.fail_plan) or (not is_plan and self.fail_safety):
            raise LLMUnavailable("All LLM providers failed.", [{"provider": "x", "ok": False}])
        obj = (self.plans.pop(0) if len(self.plans) > 1 else self.plans[0]) if is_plan else self.explanation
        value = validator(obj) if validator else obj
        return value, LLMResult(json.dumps(obj), "fake", "fake-model", [{"provider": "fake", "ok": True}], 1)

    @property
    def planner_calls(self):
        return [c for c in self.calls if c[0].startswith("You are the planning step")]

    @property
    def safety_calls(self):
        return [c for c in self.calls if not c[0].startswith("You are the planning step")]


def article(pmid="111"):
    # The default success fixture must overlap with the default query.
    # A valid PMID alone does not establish topical relevance.
    return {"pmid": pmid, "title": f"Sumatriptan for migraine: Study {pmid}",
            "journal": "J Ex", "pub_date": "2023", "authors": "A B",
            "evidence_type": "meta_analysis", "publication_types": ["Meta-Analysis"], "doi": "",
            "abstract": "This study evaluates sumatriptan treatment for acute migraine.",
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"}


def evidence_ok(pmids=("111",), relaxations=()):
    arts = [article(p) for p in pmids]
    return at._envelope("search_medical_evidence", "ok", "found", {
        "article_count": len(arts), "pmids": list(pmids), "articles": arts, "relaxations": list(relaxations),
        "search_query": "q", "high_evidence_filter": not relaxations})


def evidence_none():
    return at._envelope("search_medical_evidence", "no_results", "none", {
        "article_count": 0, "pmids": [], "articles": [], "relaxations": [], "search_query": "q"})


def evidence_error():
    return at._envelope("search_medical_evidence", "error", "PubMed could not be reached. Evidence is UNAVAILABLE.",
                        retryable=True)


def substitutes_ok(ambiguous=False):
    match = {"generic_name": "Sumatriptan Tablets IP 50mg", "unit_size": "4's", "matched_on": "generic",
             "matched_text": "x", "match_score": 99.0, "jan_aushadhi_price": 20.0, "market_average_price": 120.0,
             "price_status": "savings", "savings_amount": 100.0, "savings_percent": 83.3, "example_brands": []}
    return at._envelope("find_generic_substitute", "ok", "1 of 1", {"results": [
        {"input": "Sumatriptan 50", "found": True, "ambiguous": ambiguous, "confidence": "high", "match": match,
         "alternatives": [], "message": "", "action": ""}]})


class FakeTools:
    def __init__(self, evidence=None, substitutes=None):
        self.evidence = evidence if evidence is not None else evidence_ok()
        self.substitutes = substitutes if substitutes is not None else substitutes_ok()
        self.calls = []
        self._lock = threading.Lock()

    def __call__(self, name, arguments):
        with self._lock:
            self.calls.append((name, json.loads(json.dumps(arguments))))
        return self.evidence if name == "search_medical_evidence" else self.substitutes


_TEST_SESSION_DIRS = []

def make_agent(llm=None, tools=None):
    llm = llm or ScriptedLLM()
    tools = tools or FakeTools()
    temp_dir = tempfile.TemporaryDirectory()
    _TEST_SESSION_DIRS.append(temp_dir)
    store = SessionStore(str(Path(temp_dir.name) / "sessions.sqlite3"))
    return MedAgent(AgentDeps(llm=llm, patients=PatientStore(SAMPLE), tools=tools), session_store=store), llm, tools


# ----------------------------------------------------------------------------- validators
class ValidatorTests(unittest.TestCase):
    def test_plan_normalisation(self):
        plan = agent.validate_plan({"task": "prescription_check", "drugs": ["Telma 40", "telma 40", 5, ""],
                                    "intent": "INTERACTION", "condition": "  hypertension ", "topic": None})
        self.assertEqual(plan["drugs"], ["Telma 40"])
        self.assertEqual(plan["intent"], "interaction")
        self.assertEqual(plan["condition"], "hypertension")

    def test_plan_defaults_and_errors(self):
        plan = agent.validate_plan({"drugs": ["A", "B"], "intent": "bogus", "task": "bogus"})
        self.assertEqual((plan["intent"], plan["task"]), ("interaction", "prescription_check"))
        self.assertEqual(agent.validate_plan({"drugs": "Aspirin"})["drugs"], ["Aspirin"])
        self.assertEqual(agent.validate_plan({})["task"], "general")
        for bad in ("text", None, [1], {"drugs": {"a": 1}}):
            with self.assertRaises(ValueError):
                agent.validate_plan(bad)

    def test_explanation(self):
        ok = agent.validate_explanation({"status": "Caution", "message": "m", "pmids": [123456, "654321"]})
        self.assertEqual((ok["status"], ok["pmids"]), ("caution", ["123456", "654321"]))
        from_text = agent.validate_explanation({"status": "info", "message": "m", "evidence": "see PMID 1234567 and 7654321"})
        self.assertEqual(from_text["pmids"], ["1234567", "7654321"])
        for bad in ({"status": "approve!", "message": "m"}, {"status": "info"}, {"status": "info", "message": " "}, "x"):
            with self.assertRaises(ValueError):
                agent.validate_explanation(bad)


# ----------------------------------------------------------------------------- verdict logic
class SafetyLogicTests(unittest.TestCase):
    def test_approved_when_evidence_is_direct_and_cited(self):
        a, llm, tools = make_agent()
        r = a.ask("PAT-002", "Start Sumatriptan 50 for migraine and compare generic prices")
        self.assertEqual(r["status"], "approved")
        self.assertEqual(r["pmids"], ["111"])
        self.assertEqual(r["evidence_level"], "direct")
        self.assertIn("PMID 111", r["evidence"])
        self.assertEqual(r["sources"][0]["url"], "https://pubmed.ncbi.nlm.nih.gov/111/")
        self.assertTrue(r["savings"]["found"])
        self.assertIn("₹100.00 (83.3%) lower per pack", r["savings"]["text"])
        self.assertIn("disclaimer", r)

    def test_approved_is_downgraded_when_evidence_is_indirect(self):
        a, *_ = make_agent(tools=FakeTools(evidence=evidence_ok(relaxations=["condition dropped"])))
        r = a.ask("PAT-002", "Start Sumatriptan 50")
        self.assertEqual(r["status"], "caution")
        self.assertEqual(r["evidence_level"], "indirect")
        self.assertTrue(any("not direct" in n.lower() for n in r["audit"]["notes"]))

    def test_invented_pmids_are_removed_and_approval_needs_a_real_citation(self):
        llm = ScriptedLLM(explanation={"status": "approved", "title": "t", "message": "m", "pmids": ["999999", "111"],
                                      "claim_checks": [{"claim": "Sumatriptan is studied for acute migraine.", "pmid": "111",
                                                        "verdict": "supported",
                                                        "evidence_quote": "This study evaluates sumatriptan treatment for acute migraine.",
                                                        "rationale": "Exact fixture abstract quote."}]})
        r = make_agent(llm)[0].ask("PAT-002", "Start Sumatriptan 50")
        self.assertEqual(r["pmids"], ["111"])
        self.assertEqual(r["status"], "approved")
        self.assertTrue(any("Removed 1 citation" in n for n in r["audit"]["notes"]))
        llm = ScriptedLLM(explanation={"status": "approved", "title": "t", "message": "m", "pmids": ["999999"]})
        r = make_agent(llm)[0].ask("PAT-002", "Start Sumatriptan 50")
        self.assertEqual((r["status"], r["pmids"]), ("caution", []))
        self.assertEqual(r["evidence"], "No verifiable citation.")

    def test_allergy_blocks_even_if_the_llm_approves(self):
        llm = ScriptedLLM(plan={"task": "prescription_check", "drugs": ["Amoxicillin 500"], "intent": "safety"})
        r = make_agent(llm)[0].ask("PAT-001", "Prescribe Amoxicillin 500")
        self.assertEqual(r["status"], "blocked")
        self.assertTrue(r["title"].startswith("Blocked"))
        self.assertTrue(r["message"].startswith("Alert:"))
        self.assertIn("Literature note", r["message"])           # LLM text is labelled as not overriding the alert
        self.assertFalse(r["savings"]["found"])
        self.assertEqual([f["type"] for f in r["flags"]], ["allergy"])

    def test_cross_reactivity_makes_it_a_caution(self):
        llm = ScriptedLLM(plan={"task": "prescription_check", "drugs": ["Diclofenac 50"], "intent": "safety"})
        r = make_agent(llm)[0].ask("PAT-001", "Prescribe Diclofenac 50")
        self.assertEqual(r["status"], "caution")
        self.assertEqual(r["flags"][0]["type"], "allergy_cross_reactivity")

    def test_duplicate_therapy_is_reported(self):
        llm = ScriptedLLM(plan={"task": "prescription_check", "drugs": ["Telmisartan 40"], "intent": "safety"})
        r = make_agent(llm)[0].ask("PAT-001", "Prescribe Telmisartan 40")
        self.assertEqual(r["status"], "caution")
        self.assertIn("already taking", r["message"])

    def test_llm_blocked_stays_blocked(self):
        llm = ScriptedLLM(explanation={"status": "blocked", "title": "Contraindicated", "message": "m", "pmids": ["111"]})
        self.assertEqual(make_agent(llm)[0].ask("PAT-002", "Start Sumatriptan 50")["status"], "blocked")

    def test_unavailable_evidence_never_reaches_the_llm(self):
        a, llm, _ = make_agent(tools=FakeTools(evidence=evidence_error()))
        r = a.ask("PAT-002", "Start Sumatriptan 50 and compare generic prices")
        self.assertEqual(r["status"], "caution")
        self.assertEqual(r["evidence_level"], "unavailable")
        self.assertEqual(len(llm.safety_calls), 0)                 # no LLM call on missing evidence
        self.assertIn("could not be completed", r["message"])
        self.assertNotIn("UNAVAILABLE", r["message"])              # tool/developer wording stays out of the doctor's view
        self.assertTrue(any("Evidence tool:" in n for n in r["audit"]["notes"]))
        self.assertEqual(r["audit"]["tools"]["evidence"], "error")
        self.assertTrue(r["audit"]["tools"]["evidence_retryable"])
        self.assertTrue(r["savings"]["found"])                     # the price lookup is independent of the search

    def test_no_results_is_not_reassuring(self):
        a, llm, _ = make_agent(tools=FakeTools(evidence=evidence_none()))
        r = a.ask("PAT-002", "Start Sumatriptan 50")
        self.assertEqual((r["status"], r["evidence_level"]), ("caution", "none"))
        self.assertEqual(len(llm.safety_calls), 0)
        self.assertEqual(r["title"], "No evidence found")

    def test_llm_down_for_safety_still_lists_the_evidence(self):
        a, llm, _ = make_agent(ScriptedLLM(fail_safety=True))
        r = a.ask("PAT-002", "Start Sumatriptan 50")
        self.assertEqual(r["status"], "caution")
        self.assertIn("[PMID 111]", r["message"])
        self.assertEqual(r["pmids"], ["111"])
        self.assertTrue(any("no explanation" in str(x) for x in r["audit"]["llm"]))

    def test_ambiguous_substitute_is_called_out(self):
        a, *_ = make_agent(tools=FakeTools(substitutes=substitutes_ok(ambiguous=True)))
        self.assertIn("strength", a.ask("PAT-002", "Find a generic substitute for Sumatriptan 50")["savings"]["text"].lower())


# ----------------------------------------------------------------------------- patient switching & memory
class PatientSwitchTests(unittest.TestCase):
    def test_switching_patient_reloads_data_and_clears_memory(self):
        llm = ScriptedLLM(plans=[{"task": "prescription_check", "drugs": ["Amoxicillin 500"], "intent": "safety"},
                                 {"task": "prescription_check", "drugs": ["Amoxicillin 500"], "intent": "safety"}])
        a, *_ = make_agent(llm)
        first = a.ask("PAT-001", "Prescribe Amoxicillin 500", thread_id="s")      # penicillin allergy
        second = a.ask("PAT-002", "Prescribe Amoxicillin 500", thread_id="s")
        self.assertEqual(first["status"], "blocked")
        self.assertEqual(second["title"], "Conversation belongs to another patient")
        self.assertEqual(len(llm.planner_calls), 1)  # never reuse a patient-bound thread for another patient

    def test_same_patient_keeps_context(self):
        llm = ScriptedLLM(plans=[{"task": "prescription_check", "drugs": ["Sumatriptan 50"], "condition": "migraine",
                                  "intent": "safety"}, {"task": "followup", "drugs": ["Paracetamol"], "intent": "safety"}])
        a, *_ = make_agent(llm)
        a.ask("PAT-002", "Start Sumatriptan 50", thread_id="s")
        a.ask("PAT-002", "What about Paracetamol?", thread_id="s")
        context = json.loads(llm.planner_calls[1][1])["session_context"]
        self.assertIn("Turn 1: prescription_check about Sumatriptan 50 for migraine -> approved", context)

    def test_stale_results_do_not_leak_into_a_clarification_turn(self):
        llm = ScriptedLLM(plans=[{"task": "prescription_check", "drugs": ["Sumatriptan 50"], "intent": "safety"},
                                 {"task": "general", "drugs": [], "clarification": "Which medicine do you mean?"}])
        a, _, tools = make_agent(llm)
        a.ask("PAT-002", "Start Sumatriptan 50", thread_id="s")
        calls_after_first = len(tools.calls)
        r = a.ask("PAT-002", "and the other one?", thread_id="s")
        self.assertEqual((r["status"], r["message"]), ("info", "Which medicine do you mean?"))
        self.assertEqual(len(tools.calls), calls_after_first)                       # nothing researched
        self.assertEqual(r["pmids"], [])                                            # nothing carried over

    def test_memory_is_capped_and_extractive(self):
        llm = ScriptedLLM(plan={"task": "prescription_check", "drugs": ["Sumatriptan 50"], "intent": "safety"})
        a, *_ = make_agent(llm)
        for _ in range(8):
            a.ask("PAT-002", "Start Sumatriptan 50", thread_id="s")
        memory = a._sessions["s"]["memory"]
        self.assertEqual(len(memory), agent.MAX_MEMORY_TURNS)
        self.assertLessEqual(len(a._sessions["s"]["summary"]), agent.MAX_CONTEXT_CHARS)
        self.assertEqual(set(memory[0]), {"task", "drugs", "condition", "topic", "status", "alerts"})  # no free text

    def test_unknown_or_missing_patient(self):
        a, llm, tools = make_agent()
        r = a.ask("PAT-404", "Start Sumatriptan 50")
        self.assertEqual((r["status"], r["title"]), ("caution", "Patient not found"))
        self.assertEqual((len(llm.calls), len(tools.calls)), (0, 0))
        self.assertEqual(a.ask("", "hello")["status"], "info")
        self.assertEqual(a.ask("PAT-002", "   ")["title"], "Empty request")

    def test_threads_are_independent(self):
        a, *_ = make_agent()
        a.ask("PAT-001", "x", thread_id="one")
        a.ask("PAT-002", "x", thread_id="two")
        self.assertEqual(a._sessions["one"]["loaded_patient_id"], "PAT-001")
        self.assertEqual(a._sessions["two"]["loaded_patient_id"], "PAT-002")
        a.reset("one")
        self.assertNotIn("one", a._sessions)

    def test_concurrent_asks_do_not_interfere(self):
        a, *_ = make_agent()
        results = {}

        def worker(tid, pid):
            for _ in range(5):
                results[tid] = a.ask(pid, "Start Sumatriptan 50", thread_id=tid)

        threads = [threading.Thread(target=worker, args=(f"t{i}", "PAT-002" if i % 2 else "PAT-001")) for i in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len(results), 6)
        for i in range(6):
            self.assertEqual(a._sessions[f"t{i}"]["loaded_patient_id"], "PAT-002" if i % 2 else "PAT-001")


# ----------------------------------------------------------------------------- privacy & degradation
class PrivacyAndResilienceTests(unittest.TestCase):
    def test_patient_identity_never_reaches_llm_or_tools(self):
        llm = ScriptedLLM(plan={"task": "prescription_check", "drugs": ["Sumatriptan 50"], "intent": "safety"})
        a, _, tools = make_agent(llm)
        a.ask("PAT-001", "Prescribe Sumatriptan 50 for RAHUL sharma today")
        everything = " ".join(s + u for s, u in llm.calls) + json.dumps(tools.calls)
        for secret in ("Rahul", "RAHUL", "Sharma", "sharma", "PAT-001"):
            self.assertNotIn(secret, everything)
        self.assertIn("the patient", llm.planner_calls[0][1])

    def test_planner_failure_falls_back_to_rules(self):
        at.set_finder(GenericFinder(DB))
        try:
            a, llm, tools = make_agent(ScriptedLLM(fail_plan=True))
            r = a.ask("PAT-002", "Prescribe Sumatriptan 50 for migraine")
            self.assertEqual(r["audit"]["plan"]["source"], "rules")
            self.assertEqual(r["audit"]["plan"]["drugs"], ["Sumatriptan 50"])
            self.assertEqual(tools.calls[0][0] in ("search_medical_evidence", "find_generic_substitute"), True)
            self.assertIn(r["status"], ("approved", "caution"))
        finally:
            at.set_finder(None)

    def test_planner_and_safety_both_down_still_answers_safely(self):
        at.set_finder(GenericFinder(DB))
        try:
            a, *_ = make_agent(ScriptedLLM(fail_plan=True, fail_safety=True))
            r = a.ask("PAT-001", "Prescribe Amoxicillin 500 for infection")
            self.assertEqual(r["status"], "blocked")                  # allergy rule needs no LLM at all
            self.assertIn("penicillin", r["message"])
        finally:
            at.set_finder(None)

    def test_a_crashing_tool_is_contained(self):
        def boom(name, arguments):
            raise RuntimeError("tool exploded")

        a, *_ = make_agent(tools=boom)
        r = a.ask("PAT-002", "Start Sumatriptan 50")
        self.assertEqual((r["status"], r["evidence_level"]), ("caution", "unavailable"))
        self.assertNotIn("exploded", json.dumps(r))

    def test_a_crashing_node_stops_the_turn_safely(self):
        a, *_ = make_agent()
        with mock.patch.object(a.deps.patients, "get", side_effect=RuntimeError("db down")):
            r = a.ask("PAT-002", "Start Sumatriptan 50")
        self.assertEqual((r["status"], r["title"]), ("caution", "System error"))
        self.assertNotIn("db down", json.dumps(r))

    def test_response_is_json_serialisable_and_has_legacy_fields(self):
        r = make_agent()[0].ask("PAT-002", "Start Sumatriptan 50")
        json.dumps(r)
        for key in ("status", "title", "message", "evidence", "suggestion", "savings"):   # fields the old frontend reads
            self.assertIn(key, r)
        self.assertIn(r["status"], agent.STATUSES)

    def test_audit_block(self):
        r = make_agent()[0].ask("PAT-002", "Start Sumatriptan 50")
        audit = r["audit"]
        self.assertEqual(audit["patient_id"], "PAT-002")
        self.assertEqual(audit["tools"], {"evidence": "ok", "evidence_retryable": False, "substitute": None})
        self.assertEqual([x["step"] for x in audit["llm"]], ["plan", "safety"])


# ----------------------------------------------------------------------------- research node & real tools
class ResearchTests(unittest.TestCase):
    def test_tools_receive_clean_structured_arguments(self):
        llm = ScriptedLLM(plan={"task": "prescription_check", "drugs": ["Clopidogrel", "Omeprazole"], "condition": "CAD",
                                "intent": "interaction"})
        a, _, tools = make_agent(llm)
        a.ask("PAT-003", "Can I give Clopidogrel with Omeprazole to him?")
        by_name = dict(tools.calls)
        self.assertEqual(by_name["search_medical_evidence"], {"drugs": ["Clopidogrel", "Omeprazole"], "condition": "CAD",
                                                              "intent": "interaction", "question": None})
        self.assertNotIn("find_generic_substitute", by_name)  # interaction checks do not imply price-comparison intent

    def test_topic_question_without_drugs_searches_evidence_only(self):
        llm = ScriptedLLM(plan={"task": "research_question", "drugs": [], "topic": "hypertension diabetes guideline",
                                "intent": "guideline"})
        a, _, tools = make_agent(llm)
        a.ask("PAT-001", "Latest guideline for hypertension in diabetics?")
        self.assertEqual([c[0] for c in tools.calls], ["search_medical_evidence"])
        self.assertEqual(tools.calls[0][1]["question"], "hypertension diabetes guideline")

    def test_end_to_end_with_the_real_tools(self):
        """Real agent_tools + mocked PubMed: proves the two layers agree on every field name."""
        at.set_finder(GenericFinder(DB))
        at.clear_cache()
        # The end-to-end query is Telma 40 (telmisartan), so use a matching
        # PubMed-shaped article rather than the unrelated clopidogrel fixture.
        telmisartan_article = make_article(
            title="Telmisartan for hypertension: clinical study",
            MedlineCitation={
                "PMID": "111",
                "Article": {
                    "ArticleTitle": "Telmisartan for hypertension: clinical study",
                    "Abstract": {"AbstractText": ["Telmisartan is evaluated for treatment of hypertension."]},
                    "AuthorList": [{"LastName": "Smith", "ForeName": "Jane", "Initials": "J"}],
                    "Journal": {"Title": "Journal of Examples", "ISOAbbreviation": "J Ex",
                                "JournalIssue": {"PubDate": {"Year": "2023"}}},
                    "PublicationTypeList": ["Clinical Trial"],
                    "ELocationID": [],
                },
                "MeshHeadingList": [{"DescriptorName": "Telmisartan"}, {"DescriptorName": "Hypertension"}],
            },
            PubmedData={"ArticleIdList": []},
        )
        fake = FakeEntrez(esearch_results=[{"IdList": ["111"]}],
                          efetch_results=[{"PubmedArticle": [telmisartan_article]}])
        llm = ScriptedLLM(plan={"task": "prescription_check", "drugs": ["Telma 40"], "intent": "safety"},
                          explanation={"status": "approved", "title": "ok", "message": "fine", "pmids": ["111"],
                                       "claim_checks": [{"claim": "Telmisartan is evaluated for treatment of hypertension.",
                                                         "pmid": "111", "verdict": "supported",
                                                         "evidence_quote": "Telmisartan is evaluated for treatment of hypertension.",
                                                         "rationale": "Exact fixture abstract quote."}]})
        try:
            with mock.patch.object(pubmed, "_entrez", return_value=fake), \
                 mock.patch("medperplexity.pubmed.time.sleep", lambda *_: None):
                temp_dir = tempfile.TemporaryDirectory()
                _TEST_SESSION_DIRS.append(temp_dir)
                store = SessionStore(str(Path(temp_dir.name) / "sessions.sqlite3"))
                a = MedAgent(AgentDeps(llm=llm, patients=PatientStore(SAMPLE)), session_store=store)  # real dispatch
                r = a.ask("PAT-002", "Start Telma 40 and compare generic prices")
        finally:
            at.set_finder(None)
            at.clear_cache()
        from pprint import pprint

        print("\n===== FULL INTEGRATION RESPONSE =====")
        pprint(r)
        print("===== CLAIM SUPPORT =====")
        pprint(r.get("claim_support"))
        print("===== AUDIT =====")
        pprint(r.get("audit"))
        print("===== FLAGS =====")
        pprint(r.get("flags"))
        self.assertEqual(r["status"], "caution")
        self.assertEqual(r["claim_support"]["status"], "supported")
        self.assertEqual(r["evidence_level"], "indirect")
        self.assertEqual(r["pmids"], ["111"])
        self.assertTrue(r["savings"]["found"])
        self.assertIn("Telmisartan", r["savings"]["text"])
        self.assertEqual(r["audit"]["tools"]["evidence"], "ok")


# ----------------------------------------------------------------------------- command line
class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        import contextlib
        import io

        from medperplexity.cli import main

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_ask_command_without_any_llm(self):
        from medperplexity.llm import FallbackLLM

        at.set_finder(GenericFinder(DB))
        at.clear_cache()
        fake = FakeEntrez(esearch_results=[{"IdList": []}] * 3)
        try:
            with mock.patch.object(FallbackLLM, "from_env", return_value=FallbackLLM([])), \
                 mock.patch.object(pubmed, "_entrez", return_value=fake), \
                 mock.patch("medperplexity.pubmed.time.sleep", lambda *_: None):
                code, out, err = self.run_cli("ask", "PAT-001", "Prescribe Amoxicillin 500 for infection",
                                              "--patients", str(SAMPLE))
        finally:
            at.set_finder(None)
            at.clear_cache()
        response = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(response["status"], "blocked")        # allergy rule works with no LLM and no evidence
        self.assertNotIn("audit", response)
        self.assertIn("No LLM is configured", err)

    def test_llm_check_command(self):
        from medperplexity.llm import FallbackLLM

        class Stub:
            providers = [object()]

            def check(self):
                return [{"provider": "openrouter", "ok": True}, {"provider": "openai", "ok": False, "error": "401"}]

        with mock.patch.object(FallbackLLM, "from_env", return_value=Stub()):
            code, out, _ = self.run_cli("llm-check")
        self.assertEqual(code, 1)
        self.assertEqual(len(json.loads(out)), 2)
        with mock.patch.object(FallbackLLM, "from_env", return_value=FallbackLLM([])):
            code, _, err = self.run_cli("llm-check")
        self.assertEqual(code, 2)
        self.assertIn("OPENROUTER_API_KEY", err)


# ----------------------------------------------------------------------------- helpers & LangGraph wiring
class HelperTests(unittest.TestCase):
    def test_redact(self):
        patient = {"name": "Rahul Sharma (synthetic)"}
        self.assertEqual(agent.redact("Rahul's father, Sharma ji", patient), "the patient's father, the patient ji")
        self.assertEqual(agent.redact("nothing here", {}), "nothing here")

    def test_render_memory(self):
        text = agent.render_memory([{"task": "general", "drugs": [], "topic": "migraine", "status": "info", "alerts": []}])
        self.assertEqual(text, "Turn 1: general about migraine -> info")

    def test_build_savings_variants(self):
        self.assertEqual(agent.build_savings(None, "caution")["text"], "Price comparison unavailable.")
        self.assertEqual(agent.build_savings(substitutes_ok(), "blocked")["found"], False)
        no_match = at._envelope("find_generic_substitute", "no_results", "0 of 1", {"results": [
            {"input": "x", "found": False}]})
        self.assertEqual(agent.build_savings(no_match, "approved")["text"], "No cheaper Jan Aushadhi equivalent found.")


class GraphWiringTests(unittest.TestCase):
    def install_fake_langgraph(self):
        END = "__end__"

        class FakeGraph:
            def __init__(self, schema):
                self.schema, self.nodes, self.edges, self.entry = schema, {}, [], None

            def add_node(self, name, fn):
                self.nodes[name] = fn

            def add_edge(self, a, b):
                self.edges.append((a, b))

            def set_entry_point(self, name):
                self.entry = name

            def compile(self, checkpointer=None):
                graph = self

                class Compiled:
                    checkpointer_used = checkpointer

                    def invoke(self, state, config=None):
                        state, current = dict(state), graph.entry
                        while current != END:
                            state.update(graph.nodes[current](state))
                            current = next(b for a, b in graph.edges if a == current)
                        return state

                return Compiled()

        lg, graph_mod, ckpt, mem = (types.ModuleType(n) for n in
                                    ("langgraph", "langgraph.graph", "langgraph.checkpoint", "langgraph.checkpoint.memory"))
        graph_mod.StateGraph, graph_mod.END = FakeGraph, END
        mem.MemorySaver = type("MemorySaver", (), {})
        return {"langgraph": lg, "langgraph.graph": graph_mod, "langgraph.checkpoint": ckpt,
                "langgraph.checkpoint.memory": mem}

    def test_graph_runs_the_same_nodes_in_order(self):
        deps = AgentDeps(llm=ScriptedLLM(), patients=PatientStore(SAMPLE), tools=FakeTools())
        with mock.patch.dict(sys.modules, self.install_fake_langgraph()):
            compiled = agent.build_graph(deps)
            final = compiled.invoke({"patient_id": "PAT-002", "doctor_query": "Start Sumatriptan 50"})
        self.assertEqual(final["final_response"]["status"], "approved")
        self.assertEqual(final["memory"][0]["drugs"], ["Sumatriptan 50"])
        self.assertEqual(type(compiled.checkpointer_used).__name__, "MemorySaver")

    def test_graph_state_schema_has_the_legacy_keys(self):
        for key in ("patient_id", "doctor_query", "patient_data", "research_evidence", "jan_aushadhi_result",
                    "summary", "final_response"):
            self.assertIn(key, agent.AgentState.__annotations__)

    def test_missing_langgraph_gives_a_clear_error(self):
        with mock.patch.dict(sys.modules, {"langgraph": None, "langgraph.graph": None}):
            with self.assertRaises(ImportError) as ctx:
                agent.build_graph(AgentDeps(llm=ScriptedLLM(), patients=PatientStore(SAMPLE)))
        self.assertIn("pip install langgraph", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
