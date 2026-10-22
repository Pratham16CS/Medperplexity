"""ESearch: find PubMed IDs for a query."""
from medperplexity.config import configure_entrez


def main(term: str = "Insulin AND 2024[pdat]", retmax: int = 3) -> None:
    Entrez = configure_entrez()
    with Entrez.esearch(db="pubmed", term=term, retmax=retmax) as handle:
        record = Entrez.read(handle)

    print(f"Total matches: {record['Count']}")
    print(f"First {retmax} IDs: {list(record['IdList'])}")


if __name__ == "__main__":
    main()
