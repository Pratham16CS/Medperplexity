"""Count matching records without downloading IDs (``retmax=0``).

EGQuery (count across *all* NCBI databases) is deprecated, so we ask PubMed directly.
"""
from medperplexity.config import configure_entrez


def main(term: str = "Insulin") -> None:
    Entrez = configure_entrez()
    try:
        with Entrez.esearch(db="pubmed", term=term, retmax=0) as handle:
            record = Entrez.read(handle)
    except Exception as exc:  # network / NCBI errors
        print(f"An error occurred: {exc}")
        return
    print(f"Found {record['Count']} records for '{term}' in PubMed.")


if __name__ == "__main__":
    main()
