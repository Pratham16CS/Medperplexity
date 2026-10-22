# Using MedPerplexity as an agent tool

The package exposes two tools to an LLM agent. They are built for agents, not people: they never raise, they always
return the same JSON envelope, and they say clearly what a result *means*.

| Tool | Use it when the doctor asks about... | Backed by |
|---|---|---|
| `search_medical_evidence` | safety, interactions, contraindications, efficacy, dosing or guidelines for one or more drugs | PubMed (NCBI E-utilities) |
| `find_generic_substitute` | cost: is there a cheaper Jan Aushadhi equivalent? | `data/medicines.json` |

## The contract

Every call returns:

```json
{
  "tool": "search_medical_evidence",
  "status": "ok | no_results | invalid_input | error",
  "answered": true,
  "retryable": false,
  "message": "human/LLM-readable summary",
  "data": { "...tool specific..." },
  "meta": { "retrieved_at": "...", "elapsed_ms": 812, "cached": false, "warnings": [], "version": "0.1.0" }
}
```

| status | meaning | what the agent must do |
|---|---|---|
| `ok` | lookup ran and found something | use `data`; cite only PMIDs listed in `data.pmids` |
| `no_results` | lookup ran, nothing found | say so. **For evidence this is not proof of safety.** |
| `invalid_input` | the arguments were unusable | fix the call (see `message`) and retry once |
| `error` | the lookup could not run | say evidence/data is **unavailable**; if `retryable`, retry later. Never answer from memory as if it were evidence |

`answered` is `true` only for `ok` and `no_results`. Use it as the single "did the lookup actually happen" flag.

### Evidence specifics

* `data.articles[]`: `pmid, title, journal, pub_date, authors, evidence_type, publication_types, doi, abstract, url`.
  `evidence_type` is ranked `meta_analysis > systematic_review > guideline > randomized_trial > clinical_trial >
  observational > review > case_report > other`.
* `data.relaxations` lists anything loosened to get results (evidence-quality filter, condition, topic). If it is
  non-empty the evidence is **indirect** and the agent should say so. `assess_evidence(result)` does this for you.
* Abstracts are capped at 1,500 characters, at most 10 articles per call, so the result fits a prompt.

### Substitute specifics

* `data.results[]` has one entry per drug: `found`, `confidence` (high/medium/low), `match` (generic name, unit size,
  Jan Aushadhi price, typical brand price, saving), `alternatives`, and `ambiguous`.
* `ambiguous: true` means the same drug exists in another strength, dosage form or release type with an equally good
  score (`ambiguous_with` lists them). The agent should ask the prescriber which one is meant.
* Prices are compared **per unit** and `market_average_price` is the **median** brand price.

## Helpers for the agent's own logic

```python
from medperplexity.agent_tools import (
    dispatch, get_tool_specs, assess_evidence, format_evidence_for_prompt, validate_citations)

result   = dispatch("search_medical_evidence", {"drugs": ["clopidogrel", "omeprazole"], "intent": "interaction"})
verdict  = assess_evidence(result)               # level: direct | indirect | none | unavailable
prompt   = format_evidence_for_prompt(result)    # bounded text with [PMID ...] and explicit caveats
checked  = validate_citations(llm_pmids, result) # {"valid": [...], "invalid": [...]}  drop the invalid ones
```

## Wiring it into the LangGraph backend

Your current `research_agent` passes the doctor's whole sentence to both tools and appends the running summary to the
PubMed query. With these tools, add a small **planner** step (an LLM call with structured output, or
`get_finder().extract_drug_mentions(text)` as a deterministic fallback) that produces drug names and the clinical
intent, then call the tools with those.

```python
from medperplexity.agent_tools import dispatch, assess_evidence, format_evidence_for_prompt, validate_citations

def research_agent(state):
    plan = state["plan"]                       # {"drugs": [...], "condition": "...", "intent": "interaction"}
    evidence = dispatch("search_medical_evidence", {
        "drugs": plan["drugs"], "condition": plan.get("condition"), "intent": plan["intent"]})
    savings = dispatch("find_generic_substitute", {"drugs": plan["drugs"]})
    return {"research_evidence": evidence, "jan_aushadhi_result": savings}

def safety_agent(state):
    evidence = state["research_evidence"]
    verdict = assess_evidence(evidence)
    if verdict["level"] == "unavailable":      # hard stop BEFORE any LLM call
        return {"final_response": {"status": "caution", "title": "Evidence unavailable",
                                   "message": verdict["reason"] + " Review guidelines manually."}}
    prompt = f"""... PATIENT: {...}
    EVIDENCE:\n{format_evidence_for_prompt(evidence)}
    Cite PMIDs as a JSON list in "pmids". If EVIDENCE LEVEL is not DIRECT, say the evidence is limited."""
    decision = llm_json(prompt)
    check = validate_citations(decision.get("pmids", []), evidence)
    decision["pmids"] = check["valid"]          # LLM-invented PMIDs are discarded
    if not verdict["can_support_clear_recommendation"] and decision.get("status") == "approved":
        decision["status"] = "caution"          # no clear green light on indirect or missing evidence
    return {"final_response": decision}
```

Field mapping from the old `tools.py`/`tool1.py` result to the new one:

| Old (`search_jan_aushadhi`) | New (`find_generic_substitute`) |
|---|---|
| `found` | `data.results[i].found` |
| `drug_data.generic_name` | `data.results[i].match.generic_name` |
| `drug_data.savings_amount` ("₹41.75") | `data.results[i].match.savings_amount` (number) |
| `drug_data.savings_percentage` ("83%") | `data.results[i].match.savings_percent` (number) |
| `message` | `data.results[i].message` |

### Letting the LLM call the tools itself

```python
from medperplexity.agent_tools import get_tool_specs, call_tool_json

get_tool_specs("openai")      # or "anthropic" / "generic"
# in your loop, for each tool call the model makes:
tool_message_content = call_tool_json(tool_call.name, tool_call.arguments)   # str or dict arguments, never raises
```

With LangChain/LangGraph (`pip install langchain-core`):

```python
from medperplexity.agent_tools import langchain_tools
tools = langchain_tools()
llm_with_tools = llm.bind_tools(tools)        # and ToolNode(tools) in the graph
```

Debug a call exactly as an agent would make it:

```bash
python -m medperplexity call find_generic_substitute '{"drugs": ["Atorlip 10"]}'
python -m medperplexity call search_medical_evidence '{"drugs": ["clopidogrel","omeprazole"], "intent": "interaction"}'
python -m medperplexity specs --style openai
```

## Operational notes

| Setting | Default | Purpose |
|---|---|---|
| `NCBI_EMAIL` | none | required by NCBI; put it in `.env`, not in code |
| `NCBI_API_KEY` | none | raises NCBI's rate limit from 3 to 10 requests/second |
| `MEDPERPLEXITY_DB` | `data/medicines.json` | path to the medicine database |
| `MEDPERPLEXITY_TIMEOUT_S` | 25 | time budget per evidence search; exceeding it returns a retryable `error` |
| `MEDPERPLEXITY_CACHE_TTL_S` | 3600 | repeated identical evidence queries are served from memory (`meta.cached`) |

* The medicine database is loaded once per process (about 0.1 s) and reused.
* A search that finds nothing is retried with progressively looser terms, at most five searches, and the result
  reports exactly what was loosened.
* Search terms are sanitised so that brackets, quotes or operators typed by an LLM cannot change the PubMed query.
* **Privacy:** only drug names, a condition and a clinical intent are sent to PubMed. Never put patient names or IDs in
  tool arguments (the tool descriptions say so). Patient records belong in your own prompt, not in tool calls.
* The cache and finder are per-process. Run one worker per process or accept a cold cache per worker.
