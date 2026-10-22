"""ESpell: let NCBI correct a misspelt search term."""
from medperplexity.config import configure_entrez


def main(term: str = "Insuulin") -> None:  # intentional typo
    Entrez = configure_entrez()
    with Entrez.espell(db="pubmed", term=term) as handle:
        record = Entrez.read(handle)

    print(f"Original:  {record['Query']}")
    print(f"Corrected: {record['CorrectedQuery']}")


if __name__ == "__main__":
    main()
