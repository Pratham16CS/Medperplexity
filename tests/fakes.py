"""Test doubles that mimic the slice of Bio.Entrez the project uses (no network needed)."""
from __future__ import annotations


class StrEl(str):
    """Like Biopython's StringElement: a str carrying XML attributes."""

    def __new__(cls, text, **attributes):
        obj = super().__new__(cls, text)
        obj.attributes = attributes
        return obj


class FakeHandle:
    def __init__(self, payload):
        self.payload = payload
        self.closed = False

    def close(self):
        self.closed = True


class FakeEntrez:
    """Queue-driven fake: each esearch/efetch call pops the next scripted response."""

    def __init__(self, esearch_results=(), efetch_results=()):
        self.esearch_results = list(esearch_results)
        self.efetch_results = list(efetch_results)
        self.esearch_calls = []
        self.efetch_calls = []

    @staticmethod
    def _next(queue):
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeHandle(item)

    def esearch(self, **kwargs):
        self.esearch_calls.append(kwargs)
        return self._next(self.esearch_results)

    def efetch(self, **kwargs):
        self.efetch_calls.append(kwargs)
        return self._next(self.efetch_results)

    @staticmethod
    def read(handle):
        return handle.payload


def make_article(pmid="111", title="Clopidogrel and omeprazole <i>interaction</i>", **overrides):
    """A PubmedArticle shaped like Biopython's parsed XML."""
    article = {
        "MedlineCitation": {
            "PMID": StrEl(pmid),
            "Article": {
                "ArticleTitle": StrEl(title),
                "Abstract": {
                    "AbstractText": [
                        StrEl("Omeprazole may reduce <b>clopidogrel</b> activation.", Label="BACKGROUND"),
                        StrEl("Meta-analysis of 12 trials.", Label="METHODS"),
                    ]
                },
                "AuthorList": [
                    {"LastName": "Smith", "ForeName": "Jane", "Initials": "J",
                     "AffiliationInfo": [{"Affiliation": "Dept of Cardiology, Example University"}]},
                    {"LastName": "Doe", "ForeName": "John", "Initials": "JA",
                     "AffiliationInfo": [{"Affiliation": "Dept of Cardiology, Example University"}]},
                    {"CollectiveName": "PPI Study Group"},
                    {"LastName": "Lee", "Initials": "K"},
                ],
                "Journal": {
                    "Title": "Journal of Examples",
                    "ISOAbbreviation": "J Ex",
                    "JournalIssue": {"PubDate": {"Year": "2023", "Month": "Mar", "Day": "14"}},
                },
                "PublicationTypeList": [StrEl("Meta-Analysis"), StrEl("Journal Article")],
                "ELocationID": [],
            },
            "MeshHeadingList": [{"DescriptorName": StrEl("Clopidogrel")}, {"DescriptorName": StrEl("Omeprazole")}],
            "KeywordList": [[StrEl("drug interaction"), StrEl("CYP2C19")]],
        },
        "PubmedData": {"ArticleIdList": [StrEl("111", IdType="pubmed"), StrEl("10.1000/example", IdType="doi")]},
    }
    for key, value in overrides.items():
        article[key] = value
    return article
