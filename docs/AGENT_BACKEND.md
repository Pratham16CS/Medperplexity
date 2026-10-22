# The agent backend

`medperplexity.agent` is a rebuilt version of the Med Perplexity LangGraph backend. It answers a doctor's question
about a patient using the two tools in [`AGENT_INTEGRATION.md`](AGENT_INTEGRATION.md), with an LLM as the reasoning
step. The LLM is reached through **OpenRouter first, with Claude, OpenAI and Gemini as fallbacks**.

```
doctor question + patient id
        |
  personalize ──► load patient (reload on change, reset per-turn state, clear memory on switch)
        |
     plan ───────► LLM extracts {drugs, condition, intent}     (rule-based planner if no LLM is reachable)
        |
   research ─────► search_medical_evidence  ||  find_generic_substitute        (run in parallel)
        |
    safety ──────► code checks first (allergy, class cross-reactivity, duplicate therapy)
        |           -> evidence guard (unavailable / none never reach the LLM)
        |           -> LLM explains the evidence as JSON -> citations verified -> status = most severe of code and LLM
        |           -> savings text built from tool numbers
   summarize ────► extractive memory of the turn (no LLM)
        |
  final_response  {status, title, message, evidence, suggestion, savings, sources, pmids, evidence_level, flags, audit}
```

## What was fixed compared with the first backend

| # | Problem in the first version | Fix | Where |
|---|---|---|---|
| 1 | Switching `patient_id` inside a thread kept the previous patient's record | patient is reloaded whenever the id changes; memory is cleared at that moment; per-turn fields are reset every turn | `personalize_node` |
| 2 | The doctor's whole sentence went to the price lookup and PubMed | a planner step produces drug names / condition / intent; deterministic fallback if no LLM | `plan_node`, `validate_plan` |
| 3 | A failed PubMed call could still end in "approved" | `unavailable` / `none` evidence never reaches the LLM and always yields at least "caution" | `safety_node` + `agent_tools.assess_evidence` |
| 4 | The LLM alone decided approved / blocked | allergy, class cross-reactivity and duplicate therapy are computed in code; final status is the most severe of code and LLM | `clinical_rules.py` |
| 5 | LLM-written citations were not checked | only PMIDs the tool really returned are kept; "approved" needs direct evidence and at least one real PMID | `safety_node` |
| 6 | Free-text JSON parsed with a regex; no schema | validated JSON with one repair attempt per provider, then the next provider | `llm.py`, `validate_explanation` |
| 7 | LLM-written session summary could drift and cost a call per turn | extractive memory (drug, status, alert types), capped at 5 turns | `summarize_node` |
| 8 | Patient name and details went to the LLM | identifying fields never sent; the patient's name is redacted from the doctor's text | `patients.patient_view`, `redact` |
| 9 | One model, one failure point; `gemini-pro` hard-coded | OpenRouter (with its own model fallback) -> Claude -> OpenAI -> Gemini, all configurable | `llm.py` |
| 10 | No audit trail | every response has an `audit` block: providers tried and why, tool statuses, evidence level | `_audit` |

## Configuration

Copy `.env.example` to `.env`. It ships with the flagship models checked on 21 October 2026:

| Role | Setting | Default |
|---|---|---|
| Primary (via OpenRouter) | `OPENROUTER_MODEL` | `anthropic/claude-opus-5.5` |
| OpenRouter's own fallback chain | `OPENROUTER_FALLBACK_MODELS` | `openai/gpt-6-astra,google/gemini-4-argon` |
| Direct Claude fallback | `ANTHROPIC_MODEL` | `claude-opus-5-5` |
| Direct OpenAI fallback | `OPENAI_MODEL` | `gpt-6-astra` |
| Direct Gemini fallback | `GEMINI_MODEL` | `gemini-4-argon` (paid Google API tier) |

You only need `OPENROUTER_API_KEY`; the other providers are used if their keys are present and OpenRouter fails
(network error, rate limit, no credit, safety block, or unusable output). `LLM_PROVIDERS` sets the order.

* **Why Claude Opus 5.5 first:** at the time of writing it led OpenRouter's intelligence ranking, and Anthropic
  describes it as careful about stating only figures and citations it can support, which is what this agent needs.
  Claude Fable 5.1 is a higher, costlier tier (about 2.5x the price) with extra biology safeguards that could cause
  refusals on pharmacology questions; it is not the default, but you can try it with `OPENROUTER_MODEL`.
* **Model names go stale.** Run `python -m medperplexity llm-check` after any change; it tests each provider and
  reports pass/fail. OpenRouter IDs are `provider/model` (see openrouter.ai/models).
* **Privacy routing (OpenRouter).** Every request carries `provider.data_collection = "deny"`, so it is routed only
  to providers that do not store prompts. Set `OPENROUTER_ZDR=true` to also require zero-data-retention endpoints
  (a model with no such endpoint then fails over to the next provider).
* **Newer models reject some parameters.** If a model answers HTTP 400 naming `temperature` or `response_format`
  (GPT-6 Astra, for example, rejects `temperature`), the provider retries once without that parameter instead of
  failing over.
* OpenRouter does JSON mode only on some models; the code does not rely on it. It parses and validates the reply
  itself, whatever the model.

```bash
python -m medperplexity llm-check        # one tiny request per configured provider, pass/fail
```

## Patient data

`data/patients.json` is `{"PAT-001": {...}}` (or a list with `patient_id`). Any fields are allowed. These are
understood by the safety rules (use whichever names you like from each group):

| Meaning | Accepted keys |
|---|---|
| allergies (list, comma string, or `[{"name": ...}]`) | `allergies`, `allergy`, `drug_allergies`, `known_allergies` |
| current medicines | `current_medications`, `medications`, `current_meds`, `meds` |
| conditions | `condition_tags`, `conditions`, `diagnoses`, `problems` |

An **empty** allergy list means "none recorded". If the key is **absent**, the response carries an `info` alert that
allergies are not on record. `data/patients.sample.json` has three synthetic patients to try it.

## Running it

```bash
python -m medperplexity ask PAT-001 "Prescribe Diclofenac 50 for joint pain" --patients data/patients.sample.json
```

```python
from medperplexity.agent import MedAgent
agent = MedAgent()                                        # LLM from .env, patients from data/patients.json
response = agent.ask("PAT-001", "Prescribe Diclofenac 50 for joint pain", thread_id="session-1")
```

With LangGraph (the same nodes; use a persistent checkpointer such as `SqliteSaver` in production):

```python
from medperplexity.agent import build_graph
graph = build_graph()
result = graph.invoke({"patient_id": "PAT-001", "doctor_query": "What about Paracetamol?"},
                      config={"configurable": {"thread_id": "session-1"}})
result["final_response"]
```

## Replacing the old backend

* `agent.py` and `tools.py` are replaced by `from medperplexity.agent import ...`; `data/jan_aushadhi.json` by
  `data/medicines.json`.
* **The frontend keeps working.** `status` is still `approved | caution | blocked | info`, and `title`, `message`,
  `evidence`, `suggestion`, `savings.found/text` are unchanged. New, optional fields: `savings.items`, `sources`
  (with PubMed links), `pmids`, `evidence_level`, `flags`, `disclaimer`. Strip `audit` before returning to a browser.
* "approved" now means only: direct evidence, a verifiable citation, and no alert from the software. Consider
  showing it as "No concerns found in retrieved evidence" in the UI.

## How it fails (worst cases)

| What is down | What the doctor gets |
|---|---|
| LLM (all providers) | rule-based planner + evidence listed with PMIDs but not interpreted; status at least "caution" |
| PubMed | "literature search could not be completed"; allergy/duplicate alerts and price comparison still work; status at least "caution" |
| Both | allergy / duplicate alerts and price comparison only, with a clear statement that no evidence check was made |
| Patient record missing | "Patient not found, no safety check was possible"; no LLM or tool is called |
| Anything unexpected inside a step | "System error, review guidelines manually" (no internals shown) |

## What is and is not verified

Verified by the test suite (202 tests, no network): the request/response shapes of every provider against mocked
HTTP, fallback order and repair logic, the status rules, the patient-switch fix, citation filtering, privacy
(the patient's name never appears in any prompt or tool argument), and the LangGraph wiring against a stand-in.

**Not verified:** calls to the live OpenRouter / Claude / OpenAI / Gemini / PubMed services, and the real LangGraph
library. Run `python -m medperplexity llm-check` once with your keys, and one real `ask`, before relying on it.

## Limits to be honest about

* The safety rules cover documented allergies (with a small, non-exhaustive class table: penicillins,
  cephalosporins, sulfonamides, NSAIDs) and duplicate therapy. They are **not** a drug-interaction database;
  interactions come only from the retrieved literature, interpreted by an LLM.
* An LLM can still misread an abstract. The guards limit the damage (no invented citations, no approval on weak
  evidence, no override of software alerts) but do not make the explanation clinically validated.
* Use synthetic patients for demos. Real patient data would additionally need consent, access control, encryption
  at rest and an agreement with each LLM provider.
