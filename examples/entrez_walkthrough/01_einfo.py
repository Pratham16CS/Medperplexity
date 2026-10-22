"""EInfo: discover which search fields the PubMed database offers."""
import pandas as pd

from medperplexity.config import configure_entrez


def main() -> None:
    Entrez = configure_entrez()
    with Entrez.einfo(db="pubmed") as handle:
        record = Entrez.read(handle)

    db_info = record["DbInfo"]
    print(f"Database: {db_info['Description']}")
    print(f"Last update: {db_info['LastUpdate']}\n")
    print(pd.DataFrame(db_info["FieldList"])[["Name", "FullName", "Description"]].to_string(index=False))


if __name__ == "__main__":
    main()
