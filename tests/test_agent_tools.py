import json
import sys
import threading
import types
import typing
import unittest
from unittest import mock
from urllib.error import URLError

from tests import _paths  # noqa: F401
from tests.fakes import FakeEntrez, make_article
from medperplexity import agent_tools as at
from medperplexity import pubmed
from medperplexity.generic_finder import GenericFinder

DB = [
    {"generic_name": "Atorvastatin Tablets IP 10mg", "jan_price": 8.25, "unit_size": "10's",
     "market_avg_price": 50.0, "common_brands": ["Atorlip 10 Tablet", "Storvas 10 Tablet"]},
    {"generic_name": "Metformin Hydrochloride Tablets IP 500mg", "jan_price": 5.0, "unit_size": "10's",
     "market_avg_price": 20.0, "common_brands": ["Glycomet 500 Tablet"]},
    {"generic_name": "Metformin Hydrochloride Tablets IP 1000mg", "jan_price": 9.0, "unit_size": "10's",
     "market_avg_price": 35.0, "common_brands": ["Glycomet 1000 Tablet"]},
    {"generic_name": "Diclofenac Sodium Tablets IP 50mg", "jan_price": 3.0, "unit_size": "10's",
     "market_avg_price": 25.0, "common_brands": ["Voveran 50 Tablet"]},
]

GARBAGE = [None, "", "   ", 0, 7.5, [], {}, [None], [1, 2], [""], ["x" * 5000], "a, b, c, d, e, f, g, h, i, j, k",
           {"drugs": "x"}, ["Ünïcödé 薬"], ['"quoted" [bracket] (paren)'], ["AND"], True]


def assert_envelope(testcase, result, tool=None):
    """The contract every tool result must satisfy."""
    testcase.assertIsInstance(result, dict)
    for key in ("tool", "status", "answered", "retryable", "message", "data", "meta"):
        testcase.assertIn(key, result)
    testcase.assertIn(result["status"], at.STATUSES)
    testcase.assertEqual(result["answered"], result["status"] in ("ok", "no_results"))
    for key in ("retrieved_at", "elapsed_ms", "cached", "warnings", "version"):
        testcase.assertIn(key, result["meta"])
    if tool:
        testcase.assertEqual(result["tool"], tool)
    json.dumps(result)  # must be JSON-serialisable


@mock.patch("medperplexity.pubmed.time.sleep", lambda *_: None)
class EvidenceToolTests(unittest.TestCase):
    def setUp(self):
        at.clear_cache()

    def run_tool(self, fake, **kwargs):
        with mock.patch.object(pubmed, "_entrez", return_value=fake):
            return at.search_medical_evidence(**kwargs)

    def fake_with_hit(self):
        return FakeEntrez(esearch_results=[{"IdList": ["111"]}], efetch_results=[{"PubmedArticle": [make_article()]}])

    def test_ok_result(self):
        r = self.run_tool(self.fake_with_hit(), drugs=["clopidogrel", "omeprazole"], intent="interaction")
        assert_envelope(self, r, "search_medical_evidence")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["data"]["pmids"], ["111"])
        self.assertEqual(r["data"]["relaxations"], [])
        self.assertEqual(r["data"]["articles"][0]["evidence_type"], "meta_analysis")
        self.assertEqual(r["data"]["evidence_types"], {"meta_analysis": 1})
        self.assertIn("interaction*[Title/Abstract]", r["data"]["search_query"])
        self.assertIn("clopidogrel[Title/Abstract]", r["data"]["search_query"])

    def test_no_results_is_not_evidence_of_safety(self):
        fake = FakeEntrez(esearch_results=[{"IdList": []}] * 3)
        r = self.run_tool(fake, drugs=["somedrug"])
        assert_envelope(self, r)
        self.assertEqual(r["status"], "no_results")
        self.assertTrue(r["answered"])
        self.assertIn("NOT evidence", r["message"])
        self.assertEqual(at.assess_evidence(r)["level"], "none")

    def test_broadening_is_reported(self):
        fake = FakeEntrez(esearch_results=[{"IdList": []}, {"IdList": ["111"]}],
                          efetch_results=[{"PubmedArticle": [make_article()]}])
        r = self.run_tool(fake, drugs=["clopidogrel"], intent="interaction")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["data"]["relaxations"], ["evidence-quality filter removed"])
        self.assertTrue(any("broadened" in w for w in r["meta"]["warnings"]))
        verdict = at.assess_evidence(r)
        self.assertEqual(verdict["level"], "indirect")
        self.assertFalse(verdict["can_support_clear_recommendation"])

    def test_direct_evidence_supports_recommendation(self):
        r = self.run_tool(self.fake_with_hit(), drugs=["clopidogrel"])
        self.assertTrue(at.assess_evidence(r)["can_support_clear_recommendation"])

    def test_unreachable_pubmed_is_error_not_no_results(self):
        fake = FakeEntrez(esearch_results=[URLError("down")] * 4)
        r = self.run_tool(fake, drugs=["clopidogrel"])
        assert_envelope(self, r)
        self.assertEqual(r["status"], "error")
        self.assertFalse(r["answered"])
        self.assertTrue(r["retryable"])
        self.assertIn("UNAVAILABLE", r["message"])
        self.assertEqual(at.assess_evidence(r)["level"], "unavailable")

    def test_timeout_is_a_retryable_error(self):
        gate = threading.Event()

        def slow(*_a, **_k):
            gate.wait(0.4)  # not time.sleep: this class patches it out
            return {}

        with mock.patch.object(pubmed, "search_evidence", slow):
            r = at.search_medical_evidence(drugs=["x"], timeout_s=0.05)
        self.assertEqual(r["status"], "error")
        self.assertTrue(r["retryable"])
        self.assertIn("timed out", r["message"])

    def test_unexpected_exception_never_escapes(self):
        with mock.patch.object(pubmed, "search_evidence", side_effect=KeyError("boom")):
            r = at.search_medical_evidence(drugs=["x"])
        assert_envelope(self, r)
        self.assertEqual(r["status"], "error")
        self.assertNotIn("boom", r["message"])  # no internals leaked to the LLM

    def test_malformed_internal_result_still_returns_an_envelope(self):
        with mock.patch.object(pubmed, "search_evidence", return_value={"unexpected": True}):
            r = at.search_medical_evidence(drugs=["x"])
        assert_envelope(self, r)
        self.assertEqual(r["status"], "error")

    def test_invalid_inputs(self):
        for kwargs in ({}, {"drugs": []}, {"drugs": [""]}, {"drugs": ["x"], "intent": "poetry"}):
            r = at.search_medical_evidence(**kwargs)
            assert_envelope(self, r)
            self.assertEqual(r["status"], "invalid_input", kwargs)

    def test_string_drugs_and_clamping(self):
        fake = self.fake_with_hit()
        r = self.run_tool(fake, drugs="Clopidogrel, Omeprazole", max_results="500", min_year="abc")
        self.assertEqual(r["data"]["drugs"], ["Clopidogrel", "Omeprazole"])
        self.assertEqual(fake.esearch_calls[0]["retmax"], at.MAX_RESULTS_CAP)
        self.assertTrue(any("max_results" in w for w in r["meta"]["warnings"]))
        self.assertTrue(any("min_year" in w for w in r["meta"]["warnings"]))

    def test_cache_hit_avoids_a_second_search(self):
        fake = self.fake_with_hit()
        first = self.run_tool(fake, drugs=["clopidogrel"])
        second = self.run_tool(fake, drugs=["Clopidogrel "])  # same query, different casing/spacing
        self.assertFalse(first["meta"]["cached"])
        self.assertTrue(second["meta"]["cached"])
        self.assertEqual(len(fake.esearch_calls), 1)
        second["data"]["pmids"].append("tamper")
        third = self.run_tool(fake, drugs=["clopidogrel"])
        self.assertEqual(third["data"]["pmids"], ["111"])  # cache is not mutable from outside

    def test_errors_are_not_cached(self):
        fake = FakeEntrez(esearch_results=[URLError("down")] * 4 + [{"IdList": ["111"]}],
                          efetch_results=[{"PubmedArticle": [make_article()]}])
        self.assertEqual(self.run_tool(fake, drugs=["a"])["status"], "error")
        self.assertEqual(self.run_tool(fake, drugs=["a"])["status"], "ok")

    def test_abstract_truncation_and_query_injection_are_handled(self):
        art = make_article()
        art["MedlineCitation"]["Article"]["Abstract"]["AbstractText"] = [make_article()["MedlineCitation"]["Article"]["Abstract"]["AbstractText"][0].__class__("x" * 4000)]
        fake = FakeEntrez(esearch_results=[{"IdList": ["111"]}], efetch_results=[{"PubmedArticle": [art]}])
        r = self.run_tool(fake, drugs=['aspirin") OR 1[All Fields'])
        article = r["data"]["articles"][0]
        self.assertTrue(article["abstract_truncated"])
        self.assertLessEqual(len(article["abstract"]), 1510)
        term = fake.esearch_calls[0]["term"]
        self.assertNotIn('")', term)
        self.assertNotIn("1[All Fields", term.replace("[Title/Abstract]", ""))


class SubstituteToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        at.set_finder(GenericFinder(DB), {"records": len(DB), "source_file": "test.json", "modified": "2026-01-01"})

    @classmethod
    def tearDownClass(cls):
        at.set_finder(None)

    def test_found(self):
        r = at.find_generic_substitute(drugs=["Atorlip 10"])
        assert_envelope(self, r, "find_generic_substitute")
        self.assertEqual(r["status"], "ok")
        entry = r["data"]["results"][0]
        self.assertTrue(entry["found"])
        self.assertFalse(entry["ambiguous"])
        self.assertEqual(entry["confidence"], "high")
        self.assertEqual(entry["match"]["generic_name"], "Atorvastatin Tablets IP 10mg")
        self.assertEqual(entry["match"]["price_status"], "savings")
        self.assertIn("verify", entry["action"])
        self.assertEqual(r["data"]["database"]["records"], len(DB))

    def test_ambiguity_is_flagged_when_strength_is_missing(self):
        entry = at.find_generic_substitute(drugs=["Metformin"])["data"]["results"][0]
        self.assertTrue(entry["found"])
        self.assertTrue(entry["ambiguous"])
        self.assertIn("strength", entry["action"])

    def test_strength_parameter_resolves_ambiguity(self):
        entry = at.find_generic_substitute(drugs=["Metformin"], strength="500")["data"]["results"][0]
        self.assertFalse(entry["ambiguous"])
        self.assertTrue(entry["match"]["generic_name"].endswith("500mg"))

    def test_sentence_input_is_handled(self):
        r = at.find_generic_substitute(drugs=["Prescribe Diclofenac 50 for her joint pain tonight"])
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["data"]["results"][0]["match"]["generic_name"], "Diclofenac Sodium Tablets IP 50mg")
        self.assertTrue(any("Extracted drug names" in w for w in r["meta"]["warnings"]))

    def test_multiple_drugs_mixed_results(self):
        r = at.find_generic_substitute(drugs=["Atorlip 10", "Unknownium"])
        self.assertEqual(r["status"], "ok")
        self.assertEqual([e["found"] for e in r["data"]["results"]], [True, False])
        self.assertIn("Do not infer", r["data"]["results"][1]["action"])

    def test_nothing_found(self):
        r = at.find_generic_substitute(drugs=["Unknownium"])
        self.assertEqual(r["status"], "no_results")
        self.assertTrue(r["answered"])

    def test_text_with_no_drug_is_invalid_not_a_crash(self):
        r = at.find_generic_substitute(drugs=["the patient has had a fever since last night"])
        assert_envelope(self, r)
        self.assertEqual(r["status"], "invalid_input")

    def test_item_cap(self):
        r = at.find_generic_substitute(drugs=[f"Drug{i}" for i in range(30)])
        self.assertLessEqual(len(r["data"]["results"]), at.MAX_DRUGS)

    def test_missing_database_is_a_clean_error(self):
        at.set_finder(None)
        try:
            with mock.patch.object(at, "DEFAULT_DB_PATH", at.Path("/nonexistent/db.json")):
                r = at.find_generic_substitute(drugs=["Atorlip 10"])
            assert_envelope(self, r)
            self.assertEqual(r["status"], "error")
            self.assertIn("build", r["message"])
        finally:
            at.set_finder(GenericFinder(DB), {"records": len(DB)})


class ContractFuzzTests(unittest.TestCase):
    """Garbage in, valid envelope out: an agent must never see an exception."""

    @classmethod
    def setUpClass(cls):
        at.set_finder(GenericFinder(DB))

    @classmethod
    def tearDownClass(cls):
        at.set_finder(None)

    def test_substitute_tool_survives_garbage(self):
        for value in GARBAGE:
            assert_envelope(self, at.find_generic_substitute(drugs=value))
            assert_envelope(self, at.find_generic_substitute(drugs=["Atorlip 10"], strength=value, max_alternatives=value))

    @mock.patch("medperplexity.pubmed.time.sleep", lambda *_: None)
    def test_evidence_tool_survives_garbage(self):
        for value in GARBAGE:
            fake = FakeEntrez(esearch_results=[{"IdList": []}] * 3)
            with mock.patch.object(pubmed, "_entrez", return_value=fake):
                assert_envelope(self, at.search_medical_evidence(drugs=value, condition=value, question=value,
                                                                 intent=value, max_results=value, min_year=value))

    def test_dispatch_survives_garbage(self):
        for name in (None, 1, "", "nope", "search_medical_evidence", "find_generic_substitute"):
            for args in GARBAGE + ["{not json", "[1,2]", '{"drugs": 5}']:
                assert_envelope(self, at.dispatch(name, args))


class DispatchAndSpecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        at.set_finder(GenericFinder(DB))

    @classmethod
    def tearDownClass(cls):
        at.set_finder(None)

    def test_dispatch_with_json_string_arguments(self):
        r = at.dispatch("find_generic_substitute", '{"drugs": ["Atorlip 10"]}')
        self.assertEqual(r["status"], "ok")

    def test_dispatch_unknown_tool_and_extra_arguments(self):
        r = at.dispatch("rm_rf", {})
        self.assertEqual(r["status"], "invalid_input")
        self.assertIn("find_generic_substitute", r["message"])
        r = at.dispatch("find_generic_substitute", {"drugs": ["Atorlip 10"], "patient_name": "Rahul"})
        self.assertEqual(r["status"], "ok")
        self.assertTrue(any("patient_name" in w for w in r["meta"]["warnings"]))

    def test_call_tool_json_returns_text(self):
        text = at.call_tool_json("find_generic_substitute", {"drugs": ["Atorlip 10"]})
        self.assertEqual(json.loads(text)["status"], "ok")

    def test_specs_for_every_style(self):
        for style in ("generic", "openai", "anthropic"):
            specs = at.get_tool_specs(style)
            json.dumps(specs)
            self.assertEqual(len(specs), len(at.TOOLS))
        generic = at.get_tool_specs("generic")
        self.assertEqual({s["name"] for s in generic}, set(at.TOOLS))
        for spec in generic:
            self.assertEqual(spec["parameters"]["type"], "object")
            self.assertIn("drugs", spec["parameters"]["required"])
            self.assertGreater(len(spec["description"]), 100)
        self.assertEqual(at.get_tool_specs("openai")[0]["type"], "function")
        self.assertIn("input_schema", at.get_tool_specs("anthropic")[0])
        with self.assertRaises(ValueError):
            at.get_tool_specs("nope")

    def test_spec_enum_matches_implementation(self):
        enum = at.TOOLS["search_medical_evidence"].parameters["properties"]["intent"]["enum"]
        self.assertEqual(enum, list(pubmed.INTENTS))
        self.assertEqual(set(typing.get_args(at.IntentName)), set(pubmed.INTENTS))

    def test_schema_properties_match_function_signatures(self):
        import inspect

        for tool in at.TOOLS.values():
            params = set(inspect.signature(tool.func).parameters)
            self.assertTrue(set(tool.parameters["properties"]) <= params, tool.name)

    def test_langchain_adapter_with_stub(self):
        class StubTool:
            def __init__(self, func, name, description):
                self.func, self.name, self.description = func, name, description

            @classmethod
            def from_function(cls, func, name, description, **_):
                return cls(func, name, description)

        core, tools_mod = types.ModuleType("langchain_core"), types.ModuleType("langchain_core.tools")
        tools_mod.StructuredTool = StubTool
        with mock.patch.dict(sys.modules, {"langchain_core": core, "langchain_core.tools": tools_mod}):
            tools = at.langchain_tools()
        self.assertEqual({t.name for t in tools}, set(at.TOOLS))
        sub = next(t for t in tools if t.name == "find_generic_substitute")
        self.assertEqual(json.loads(sub.func(drugs=["Atorlip 10"]))["status"], "ok")
        # annotations must be resolvable (LangChain evaluates them to build the argument schema)
        for tool in tools:
            typing.get_type_hints(tool.func)

    def test_langchain_missing_gives_clear_error(self):
        with mock.patch.dict(sys.modules, {"langchain_core": None, "langchain_core.tools": None}):
            with self.assertRaises(ImportError):
                at.langchain_tools()


class CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        at.set_finder(GenericFinder(DB))

    @classmethod
    def tearDownClass(cls):
        at.set_finder(None)

    def run_cli(self, *argv):
        import contextlib
        import io

        from medperplexity.cli import main

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(list(argv))
        return code, json.loads(buffer.getvalue())

    def test_call_command(self):
        code, out = self.run_cli("call", "find_generic_substitute", '{"drugs": ["Atorlip 10"]}')
        self.assertEqual(code, 0)
        self.assertEqual(out["status"], "ok")
        code, out = self.run_cli("call", "nope")
        self.assertEqual(code, 1)
        self.assertEqual(out["status"], "invalid_input")

    def test_specs_command(self):
        code, out = self.run_cli("specs", "--style", "openai")
        self.assertEqual(code, 0)
        self.assertEqual({s["function"]["name"] for s in out}, set(at.TOOLS))


class HelperTests(unittest.TestCase):
    def ok_result(self, relaxations=()):
        article = {"pmid": "111", "title": "T", "journal": "J", "pub_date": "2023", "evidence_type": "meta_analysis",
                   "abstract": "A" * 3000, "url": "https://pubmed.ncbi.nlm.nih.gov/111/"}
        return {"status": "ok", "message": "", "data": {"article_count": 1, "pmids": ["111"], "articles": [article] * 5,
                                                         "relaxations": list(relaxations), "search_query": "q"}}

    def test_prompt_block_is_bounded_and_cites_pmids(self):
        text = at.format_evidence_for_prompt(self.ok_result(), max_chars=2000)
        self.assertLessEqual(len(text), 2000)
        self.assertIn("[PMID 111]", text)
        self.assertIn("EVIDENCE LEVEL: DIRECT", text)

    def test_prompt_block_for_failures_is_explicit(self):
        none = at.format_evidence_for_prompt({"status": "no_results", "data": {}})
        self.assertIn("NONE", none)
        self.assertIn("not evidence of safety", none)
        failed = at.format_evidence_for_prompt({"status": "error", "message": "PubMed down", "data": {}})
        self.assertIn("UNAVAILABLE", failed)
        self.assertNotIn("[PMID", failed)

    def test_validate_citations(self):
        result = self.ok_result()
        check = at.validate_citations(["111", 111, "999", " 111 "], result)
        self.assertEqual(check["valid"], ["111", "111", "111"])
        self.assertEqual(check["invalid"], ["999"])
        self.assertEqual(at.validate_citations(None, result), {"valid": [], "invalid": []})

    def test_indirect_evidence_is_labelled(self):
        text = at.format_evidence_for_prompt(self.ok_result(["condition dropped"]))
        self.assertIn("INDIRECT", text)


if __name__ == "__main__":
    unittest.main()
