import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import _paths  # noqa: F401
from tests.fakes import FakeEntrez, make_article
from medperplexity import pubmed, pubmed_export as ex


class QueryBuildingTests(unittest.TestCase):
    def test_format_author(self):
        self.assertEqual(ex.format_author("Anthony Fauci"), "Fauci A")
        self.assertEqual(ex.format_author("Fauci AS"), "Fauci AS")
        self.assertEqual(ex.format_author("Madonna"), "Madonna")

    def test_build_query(self):
        q = ex.build_query(["Anthony Fauci", "Mehmet Oz"], ["RNA", "cardiovascular"], "2012/03/01", "2022/12/31")
        self.assertEqual(
            q,
            '(Fauci A[Author] OR Oz M[Author]) AND (RNA[Title/Abstract] OR cardiovascular[Title/Abstract])'
            ' AND ("2012/03/01"[Date - Create] : "2022/12/31"[Date - Create])',
        )

    def test_build_query_requires_something(self):
        with self.assertRaises(ValueError):
            ex.build_query()

    def test_open_ended_dates(self):
        self.assertIn('"3000"[Date - Create]', ex.build_query(topics=["RNA"], start="2020/01/01"))


@mock.patch("medperplexity.pubmed.time.sleep", lambda *_: None)
class ExportTests(unittest.TestCase):
    def test_run_export_writes_excel(self):
        import pandas as pd

        art = make_article()
        art["MedlineCitation"]["Article"]["ArticleTitle"] = "Title\x01Control"
        fake = FakeEntrez(esearch_results=[{"IdList": ["111"]}], efetch_results=[{"PubmedArticle": [art]}])
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pubmed, "_entrez", return_value=fake):
            out = Path(tmp) / "nested" / "results.xlsx"
            summary = ex.run_export(["Jane Smith"], ["omeprazole"], None, None, 5, out)
            self.assertEqual(summary["records"], 1)
            df = pd.read_excel(out, dtype=str)
        self.assertEqual(list(df.columns), ex.COLUMNS)
        row = df.iloc[0]
        self.assertEqual(row["PMID"], "111")
        self.assertEqual(row["DOI"], "10.1000/example")
        self.assertEqual(row["Title"], "TitleControl")
        self.assertIn("Smith J", row["Authors"])
        self.assertEqual(row["MeSH_Terms"], "Clopidogrel, Omeprazole")
        self.assertEqual(row["Keywords"], "drug interaction, CYP2C19")
        self.assertEqual(fake.efetch_calls[0]["id"], "111")

    def test_missing_abstract_exports_blank(self):
        art = make_article()
        del art["MedlineCitation"]["Article"]["Abstract"]
        df = ex.records_to_dataframe([pubmed.parse_article(art)])
        self.assertEqual(df.loc[0, "Abstract"], "")


if __name__ == "__main__":
    unittest.main()
