import unittest
from unittest import mock
from urllib.error import URLError

from tests import _paths  # noqa: F401
from tests.fakes import FakeEntrez, StrEl, make_article
from medperplexity import pubmed


class TextHelpersTests(unittest.TestCase):
    def test_simplify_query(self):
        self.assertEqual(pubmed.simplify_query("Can I prescribe Clopidogrel with Omeprazole?"),
                         "Clopidogrel Omeprazole")
        self.assertEqual(pubmed.simplify_query("metformin vitamin B12 deficiency."),
                         "metformin vitamin B12 deficiency")

    def test_simplify_query_never_returns_empty(self):
        self.assertEqual(pubmed.simplify_query("can I?"), "can I?")

    def test_clean_xml_text(self):
        self.assertEqual(pubmed.clean_xml_text("a <i>b</i>  <sup>2</sup>\n c"), "a b 2 c")
        self.assertEqual(pubmed.clean_xml_text(None), "")

    def test_build_search_term(self):
        strict = pubmed.build_search_term("aspirin", strict_mode=True, min_year=2020)
        self.assertIn("Meta-Analysis[pt]", strict)
        self.assertIn('"2020/01/01"[Date - Publication]', strict)
        self.assertIn("English[Language]", strict)
        self.assertNotIn("Meta-Analysis[pt]", pubmed.build_search_term("aspirin", strict_mode=False))


class ParsingTests(unittest.TestCase):
    def test_structured_abstract_keeps_labels_and_strips_tags(self):
        text = pubmed.extract_abstract_text(make_article())
        self.assertEqual(text, "BACKGROUND: Omeprazole may reduce clopidogrel activation. METHODS: Meta-analysis of 12 trials.")

    def test_missing_abstract(self):
        art = make_article()
        del art["MedlineCitation"]["Article"]["Abstract"]
        self.assertEqual(pubmed.extract_abstract_text(art), "No Abstract Available.")

    def test_dates(self):
        self.assertEqual(pubmed.get_pub_date(make_article()), "2023 Mar 14")
        art = make_article()
        art["MedlineCitation"]["Article"]["Journal"]["JournalIssue"]["PubDate"] = {"MedlineDate": "2022 Nov-Dec"}
        self.assertEqual(pubmed.get_pub_date(art), "2022 Nov-Dec")
        art["MedlineCitation"]["Article"]["Journal"]["JournalIssue"]["PubDate"] = {}
        art["MedlineCitation"]["Article"]["ArticleDate"] = [{"Year": "2024", "Month": "01", "Day": "05"}]
        self.assertEqual(pubmed.get_pub_date(art), "2024 01 05 (Epub)")
        art["MedlineCitation"]["Article"]["ArticleDate"] = []
        self.assertEqual(pubmed.get_pub_date(art), "Unknown Date")

    def test_parse_article(self):
        p = pubmed.parse_article(make_article())
        self.assertEqual(p["pmid"], "111")
        self.assertEqual(p["title"], "Clopidogrel and omeprazole interaction")
        self.assertEqual(p["journal"], "J Ex")
        self.assertEqual(p["authors"], ["Smith J", "Doe JA", "PPI Study Group", "Lee K"])
        self.assertEqual(p["affiliations"], ["Dept of Cardiology, Example University"])  # de-duplicated
        self.assertEqual(p["mesh_terms"], ["Clopidogrel", "Omeprazole"])
        self.assertEqual(p["keywords"], ["drug interaction", "CYP2C19"])
        self.assertEqual(p["doi"], "10.1000/example")
        self.assertEqual(p["publication_types"], ["Meta-Analysis", "Journal Article"])
        self.assertEqual(p["url"], "https://pubmed.ncbi.nlm.nih.gov/111/")

    def test_parse_sparse_article_does_not_crash(self):
        p = pubmed.parse_article({"MedlineCitation": {"PMID": StrEl("9"), "Article": {}}})
        self.assertEqual(p["title"], "No Title")
        self.assertEqual(p["journal"], "Unknown Journal")
        self.assertEqual(p["authors"], [])


@mock.patch("medperplexity.pubmed.time.sleep", lambda *_: None)
class QueryToolTests(unittest.TestCase):
    def run_tool(self, fake, question="Can I prescribe Clopidogrel with Omeprazole?"):
        with mock.patch.object(pubmed, "_entrez", return_value=fake):
            return pubmed.query_pubmed_realtime(question)

    def test_high_evidence_hit(self):
        fake = FakeEntrez(esearch_results=[{"IdList": ["111"]}],
                          efetch_results=[{"PubmedArticle": [make_article()]}])
        out = self.run_tool(fake)
        self.assertEqual(out["status"], "success")
        self.assertEqual(out["strategy"], "high_evidence")
        self.assertEqual(out["search_query"], "Clopidogrel Omeprazole")
        self.assertEqual(out["articles"][0]["authors"], "Smith J, Doe JA, PPI Study Group et al.")
        self.assertIn("Meta-Analysis[pt]", fake.esearch_calls[0]["term"])
        self.assertEqual(len(fake.efetch_calls), 1)  # one batched fetch

    def test_falls_back_to_broad_search(self):
        fake = FakeEntrez(esearch_results=[{"IdList": []}, {"IdList": ["111", "222"]}],
                          efetch_results=[{"PubmedArticle": [make_article("111"), make_article("222")]}])
        out = self.run_tool(fake)
        self.assertEqual(out["strategy"], "broad")
        self.assertEqual(out["evidence_count"], 2)
        self.assertNotIn("Meta-Analysis[pt]", fake.esearch_calls[1]["term"])
        self.assertEqual(fake.efetch_calls[0]["id"], "111,222")

    def test_falls_back_to_original_wording_then_reports_no_results(self):
        fake = FakeEntrez(esearch_results=[{"IdList": []}, {"IdList": []}, {"IdList": []}])
        out = self.run_tool(fake)
        self.assertEqual(out, {"status": "error", "question": "Can I prescribe Clopidogrel with Omeprazole?",
                               "message": "No results found."})
        self.assertEqual(len(fake.esearch_calls), 3)

    def test_transient_error_is_retried(self):
        fake = FakeEntrez(esearch_results=[URLError("boom"), {"IdList": ["111"]}],
                          efetch_results=[{"PubmedArticle": [make_article()]}])
        self.assertEqual(self.run_tool(fake)["status"], "success")
        self.assertEqual(len(fake.esearch_calls), 2)

    def test_persistent_error_returns_error_status(self):
        fake = FakeEntrez(esearch_results=[URLError("down")] * 4)
        out = self.run_tool(fake)
        self.assertEqual(out["status"], "error")
        self.assertIn("failed after 4 attempts", out["message"])

    def test_handles_are_closed(self):
        """Every NCBI response handle must be closed (no leaked connections)."""
        handles = []
        fake = FakeEntrez(esearch_results=[{"IdList": []}])
        original = fake.esearch

        def spy(**kw):
            h = original(**kw)
            handles.append(h)
            return h

        fake.esearch = spy
        with mock.patch.object(pubmed, "_entrez", return_value=fake):
            pubmed.search_pubmed_ids("aspirin")
        self.assertTrue(all(h.closed for h in handles))

    def test_json_wrapper(self):
        fake = FakeEntrez(esearch_results=[{"IdList": ["111"]}],
                          efetch_results=[{"PubmedArticle": [make_article()]}])
        with mock.patch.object(pubmed, "_entrez", return_value=fake):
            text = pubmed.query_pubmed_realtime_json("Clopidogrel Omeprazole")
        self.assertIn('"status": "success"', text)

    def test_fetch_batches_large_id_lists(self):
        ids = [str(i) for i in range(250)]
        fake = FakeEntrez(efetch_results=[{"PubmedArticle": []}] * 3)
        with mock.patch.object(pubmed, "_entrez", return_value=fake):
            pubmed.fetch_pubmed_articles(ids, batch_size=100)
        self.assertEqual([len(c["id"].split(",")) for c in fake.efetch_calls], [100, 100, 50])


if __name__ == "__main__":
    unittest.main()
