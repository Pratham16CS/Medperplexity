"""EPost -> ESummary -> EFetch -> ELink -> ECitMatch in one pipeline.

The NCBI *history server* lets you upload a list of IDs once (EPost) and then refer to
them with a WebEnv/QueryKey pair instead of re-sending the IDs on every request.
"""
from medperplexity.config import configure_entrez


def main() -> None:
    Entrez = configure_entrez()

    # --- ESearch: a few PMIDs to work with ---------------------------------------------
    with Entrez.esearch(db="pubmed", term="Insulin AND 2024[pdat]", retmax=3) as handle:
        id_list = list(Entrez.read(handle)["IdList"])
    print(f"Found IDs: {id_list}")

    # --- EPost: upload IDs to the history server ---------------------------------------
    print("\n--- EPost (upload to history) ---")
    with Entrez.epost(db="pubmed", id=",".join(id_list)) as handle:
        posted = Entrez.read(handle)
    webenv, query_key = posted["WebEnv"], posted["QueryKey"]
    print(f"Uploaded. WebEnv: {webenv[:10]}...  QueryKey: {query_key}")

    # --- ESummary: titles, using the history server instead of sending IDs again -------
    print("\n--- ESummary (document summaries) ---")
    with Entrez.esummary(db="pubmed", query_key=query_key, WebEnv=webenv) as handle:
        for i, doc in enumerate(Entrez.read(handle), start=1):
            print(f"{i}: {doc['Title']}")

    # --- EFetch: the full abstract of the first record ---------------------------------
    print("\n--- EFetch (abstract as text) ---")
    target_id = id_list[0]
    with Entrez.efetch(db="pubmed", id=target_id, rettype="abstract", retmode="text") as handle:
        print(f"Abstract for {target_id}:\n{handle.read()[:300]}...")

    # --- ELink: which Gene records does this paper link to? ----------------------------
    print("\n--- ELink (cross-database links) ---")
    with Entrez.elink(dbfrom="pubmed", db="gene", id=target_id) as handle:
        link_sets = Entrez.read(handle)
    try:
        links = link_sets[0]["LinkSetDb"][0]["Link"]
        print(f"PubMed ID {target_id} is linked to Gene IDs: {[link['Id'] for link in links]}")
    except (IndexError, KeyError):
        print("No linked genes found for this paper.")

    # --- ECitMatch: citation -> PMID ---------------------------------------------------
    # bdata format: journal|year|volume|first page|author|your-own-key|   (one citation per line)
    print("\n--- ECitMatch (find PMID by citation) ---")
    citation = "Science|1991|254|1279|Wang|citation_1|"
    with Entrez.ecitmatch(db="pubmed", bdata=citation) as handle:
        print(f"Citation match: {handle.read().strip()}")


if __name__ == "__main__":
    main()
