"""Recover a paper from a vague citation by broadening the search.

Searching for an exact page number ("page 1279") is brittle, so we search for the
journal + year + topic and read the *real* page numbers from the summaries.
"""
from medperplexity.config import configure_entrez


def main(query: str = "Science[Journal] AND 1991[PDAT] AND Insulin[All Fields]") -> None:
    Entrez = configure_entrez()
    print("--- Searching for the mystery paper ---")

    with Entrez.esearch(db="pubmed", term=query, retmax=20) as handle:
        record = Entrez.read(handle)
    print(f"Found {record['Count']} candidates.\n")

    id_list = list(record["IdList"])
    if not id_list:
        print("No papers found. Are you sure it was about Insulin?")
        return

    with Entrez.esummary(db="pubmed", id=",".join(id_list)) as handle:
        for doc in Entrez.read(handle):
            print(f"ID: {doc['Id']}")
            print(f"Title: {doc['Title']}")
            print(f"Pages: {doc['Pages']}")  # the REAL page range
            print("-" * 30)


if __name__ == "__main__":
    main()
