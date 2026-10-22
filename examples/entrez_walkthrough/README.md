# Entrez (NCBI E-utilities) walkthrough

These scripts document how the project's PubMed layer was built, one E-utility at a time,
straight from the NCBI/Biopython documentation. Run them in order after:

```bash
pip install -e .                 # from the repository root
cp .env.example .env             # then put your email in NCBI_EMAIL
python examples/entrez_walkthrough/01_einfo.py
```

| Script | E-utility | What it shows |
|---|---|---|
| `01_einfo.py` | EInfo | Which search fields (Author, Journal, ...) PubMed supports |
| `02_espell.py` | ESpell | Spelling suggestions for a query term |
| `03_esearch.py` | ESearch | Searching PubMed and getting PMIDs |
| `04_count_records.py` | ESearch (`retmax=0`) | Counting results without downloading IDs (modern replacement for EGQuery) |
| `05_history_server_pipeline.py` | EPost, ESummary, EFetch, ELink, ECitMatch | The NCBI history server, abstracts, cross-database links, citation lookup |
| `06_find_paper_by_citation.py` | ESearch + ESummary | Recovering a paper when you only half-remember the citation |

The production code that grew out of this lives in `src/medperplexity/pubmed.py`.
These scripts call the live NCBI service, so they need an internet connection.
