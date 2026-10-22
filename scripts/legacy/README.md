# Original embedding-based data pipeline (history)

These four scripts are the **original data-processing pipeline**, run on Google Colab with a GPU. They are kept
unmodified so the project's history and its ML component are visible. They are **not** needed to run
MedPerplexity: the current database is produced by `python -m medperplexity build`
(`src/medperplexity/build_database.py`), which is deterministic and runs in about 10 seconds on a CPU.

**Idea:** embed every Jan Aushadhi product and every brand (273,929 rows) with the biomedical sentence model
`pritamdeka/S-PubMedBert-MS-MARCO`, retrieve the nearest brands by cosine similarity, filter them with safety rules,
and compare prices. Encoding the brand catalogue took about 9 minutes per run on a GPU.

| Script | Output | What changed |
|---|---|---|
| `v1_semantic_threshold.py` | `vector_medicine_db.json` | Top 10 neighbours, cosine similarity must be at least 0.90; brand must cost more than the generic. Mapped 2,274 / 2,439, but with no form or strength check. |
| `v2_form_and_number_validator.py` | `vector_medicine_db.json` | Top 20 neighbours plus a validator: same dosage form (from the brand name) and at least one shared number. |
| `v3_final_validator.py` | `final_medicine_db.json` | Richer form keywords, and any number of 100 or more must match exactly. **Mapped 2,042 / 2,439. This produced the database the app first shipped with.** |
| `v4_chemical_overlap.py` | `safe_medicine_db.json` | Adds a device filter and requires a shared chemical word between the generic name and the brand's salt composition. |

## Known weaknesses (why `build_database.py` replaced them)

* **Prices were biased upward.** Only brands *more expensive* than the Jan Aushadhi price were kept, sorted high to
  low, and the five most expensive were averaged. In the shipped file 100% of stored brands cost more than the
  generic. The stored "market average" was typically 1.27x the median brand price found by the rebuild, and the median
  claimed saving was 76% there vs 69% with the median method.
* **Pack size and release type were ignored** (10 capsules compared with a strip of 30; plain vs extended-release).
* **Validation used the brand name, not the salt composition**, and "share at least one number" or "share one chemical
  word" lets combination products through (e.g. an Aspirin + Atorvastatin capsule matched to Aspirin).
* **Only 20 nearest neighbours** were considered per product, however many brands exist.
* Needs a GPU, a 438 MB model download, and about 9 minutes per run; results can change with the model version.

What the ML approach did well, and what to carry forward: the embeddings find spelling variants and brand text that
rules miss. A good next step is a hybrid: use the embedding model only to *retrieve candidates* and keep the strict
ingredient, strength, form and pack checks from `build_database.py` as the *decision*.
