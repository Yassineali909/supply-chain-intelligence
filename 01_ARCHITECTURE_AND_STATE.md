# ARCHITECTURE & CURRENT STATE

Full technical map. Read 00_HANDOFF_README.md first. Numbers here (test count, etc.) are
as of the end of the text-to-SQL + Qdrant session — CONFIRM them live via file 03 step 1.

---

## 1. The data layer (the "world")

### Deterministic generator — `datagen/` package
Produces the entire synthetic world reproducibly from one seed (`config.SEED`).
Run: `python -m datagen.run --persist --docs`. Eight staged steps (seed → reference →
orders → shipments+levers [the causal heart] → deliveries → invoices → incidents →
performance). Hidden levers (reliability_tier, perf_trend, congestion_season,
incidents.root_cause_id) bias the data but are STRIPPED from the agent-visible schema.
Real RC-06 shipment codes for the current seed: **SH-4493, SH-5268, SH-5761, SH-6010,
SH-6259** (flag NOT persisted — by design; they have CONTEXTUAL docs but NO DIRECT doc).

### PostgreSQL — source of truth — `datagen/writers/postgres_writer.py`
DB `meridian`. 16 business tables, ~23,256 rows. Idempotent. Hidden-lever columns stripped.
Key tables: shipments, routes, ports, carriers, warehouses, deliveries, suppliers,
purchase_orders, order_items, invoices, incidents, supplier_performance, customers, products
(+ 2 more to reach 16 — CONFIRM the full list with `\dt`; it matters for the text-to-SQL
allowlist, see §2).

### Documents — `datagen/docs/` + `artifacts/documents/`
~2746 JSON docs. 824 DIRECT (carry root_cause_id) + 1922 CONTEXTUAL. RC-06 targets have
CONTEXTUAL docs but NO DIRECT doc — the basis of the honest refusal. Each doc: {doc_id,
text, metadata{shipment_code, relevance, ...}, root_cause_id}.

### Neo4j — graph projection — `datagen/graph_projection.py`
Built FROM Postgres. ~11,863 nodes, ~23,770 rels. Idempotent. Password `devpass123`.

### Qdrant — vector store (NEW) — `rc07_vertical_slice/qdrant_store.py`
On-disk local mode at `rc07_vertical_slice/qdrant_data/` (GIT-IGNORED; rebuilt from docs,
never committed). 2746 docs embedded with **Ollama nomic-embed-text (768-dim)**. Payload
per point: {doc (the whole original doc), codes (whole SH- codes it mentions), doc_id}.
Built by `build_qdrant_index.py`. NO server/daemon needed (local mode).

---

## 2. The agent layer — `rc07_vertical_slice/` package

(Misleading name — started as the RC-07 slice, now the WHOLE agent.)

### The contract — `agent_contract.py`
Pydantic `AgentResponse` = {schema_version, run_id, question, outcome, answer, claims[],
evidence[], tool_trace[], verification, timing}. Enums: `Outcome`
(SUPPORTED/PARTIALLY_SUPPORTED/INSUFFICIENT_EVIDENCE), `ClaimType`
(ENTITY_FACT/NUMERIC/RELATIONSHIP/TREND/CAUSAL/COMPARATIVE/**AGGREGATE**), `SupportStatus`,
`SourceType` (SQL/DOCUMENT/GRAPH), `Relevance` (DIRECT/CONTEXTUAL/CONTRADICTORY). Evidence =
{evidence_id, source_type, source_ref, locator{}, fact, relevance}. Claim = {claim_id, text,
claim_type, support_status, evidence_ids[min 1]}. ToolTraceEntry.tool is a Literal:
{query_database, search_documents, graph_query, verify_evidence}. **AGGREGATE was ADDED this
session** (additive — see §verifier).

### The verifier — `verifier.py` (HARDENED, MUTATION-TESTED)
`verify_response(response)` gates every claim. Checks: CLAIM_EVIDENCE_BINDING,
EVIDENCE_PRODUCED_BY_TOOL, NUMERIC_CLAIM_MATCHES_SQL (DAY-valued only — `_DELAY_RE`/
`_NUM_DAYS_RE` match "N days", NOT "Nd" or bare counts), COMPARATIVE_CLAIM_MATCHES_SQL,
**AGGREGATE_CLAIM_MATCHES_SQL (NEW)**, CAUSAL_REQUIRES_DIRECT_DOCUMENTARY_EVIDENCE,
LEGITIMATE_PARTIAL_OUTCOME.
- **AGGREGATE check (NEW, additive):** for text-to-SQL numeric results that are NOT
  day-valued (counts, sums, grouped values). Extracts the ONE standalone value from the
  claim (`_VALUE_RE = (?<![\w.\-])(\d+(?:\.\d+)?)(?!\d)`, which IGNORES digits glued to
  entity codes like CR3/S07/WH-2/Q1/SH-4921) and confirms it appears in the SQL evidence.
  It's a TRANSCRIPTION guard (claim value == SQL result), NOT a semantic guarantee. Verified:
  a count marked NUMERIC fails closed (days-only extractor), which is WHY AGGREGATE exists.
  The loop runs ONLY for AGGREGATE claims, so the 47 original tests were untouched.

### The tools
- `postgres_tool.py` — read-only parameterized SQL for the 7 scenarios + ranking. Shared
  `_run()`. NOT text-to-SQL (that is the guardrail path below).
- `document_store.py` — JSON-directory doc search (exact shipment-code lookup). Still the
  default backend.
- `document_retrieval.py` (NEW) — backend SWITCH exposing the SAME `search_documents(root,
  code, *, evidence_id, trace_call_id)` signature. `USE_QDRANT=1` → Qdrant payload-filter
  exact lookup; else JSON. Safe fallback if index/qdrant-client missing. rc07.py + planner.py
  import search_documents from HERE now.
- `qdrant_store.py` (NEW) — `QdrantDocumentStore`: `lookup_by_code`/`search_documents`
  (EXACT, payload filter — RC-06-preserving, returns [] for absent codes) + `semantic_search`
  (vector). Embedders: `hashing_embedder` (tests), `bag_of_words_embedder` (semantic tests),
  `make_ollama_embedder` (prod, nomic-embed-text).
- `graph_tool.py` — Neo4j Cypher (RC-05).

### Text-to-SQL path (NEW — the headline of the last session)
Thesis: every other investigation is Option A (LLM never writes SQL). Text-to-SQL
deliberately lets the LLM WRITE SQL while keeping safety via layered deterministic guardrails.
- `sql_guardrail.py` — Layers 2–4. `validate_sql(sql)`: sqlglot PARSE (not regex) → exactly
  ONE statement AND it's a plain SELECT (rejects writes/DDL/stacked/UNION/SELECT-INTO) →
  TABLE ALLOWLIST `BUSINESS_TABLES` (CTE names skipped, real tables inside CTEs still checked;
  blocks pg_catalog/information_schema/cross-db) → dangerous-function denylist (pg_read_file,
  dblink, pg_sleep…) → FORCED LIMIT (inject/cap at 1000). Executes the RE-RENDERED AST.
  **NOTE: `BUSINESS_TABLES` has 14 of 16 tables — CONFIRM against live schema and fill it.**
- `sql_executor.py` — Layer 1 (read-only) + Layer 4 timeout. psycopg3, `read_only=True` +
  `default_transaction_read_only=on` + `statement_timeout`. CONFIRMED live: a bypassed DELETE
  is rejected by Postgres; timeout aborts. `python -m rc07_vertical_slice.sql_executor` (or
  `python sql_executor.py`) runs the self-check. Production upgrade noted: a dedicated
  SELECT-only role instead of SET TRANSACTION READ ONLY.
- `analytical_draft.py` — the LLM DRAFTS. Schema-aware prompt listing ONLY allowlisted
  tables/columns + FEW-SHOT exemplars (count, join-to-resolve-a-code, average, GROUP BY, and
  a "per/by/for each → GROUP BY" RULE). `draft_and_validate(llm, question, schema)` →
  fence/prose strip → validate → bounded retry (re-prompts once with the rejection reason).
- `analytical.py` — `investigate_analytical(...)`: draft → validate → read-only execute →
  build AGGREGATE claim(s) → verify. SCALAR (1×1) → one claim. GROUPED (GROUP BY, N×2) → ONE
  AGGREGATE CLAIM PER ROW, each verified; group LABEL lives in the evidence LOCATOR (never the
  scanned claim text, so a numeric label like a month can't pollute value extraction); capped
  at MAX_GROUPS=25; refuses non-numeric value column / 3+ cols / two-metrics-without-GROUP-BY.
  Also holds `is_analytical_question(q)` (the router predicate). HONEST LIMIT: the AGGREGATE
  check guarantees transcription (claim == SQL result), NOT that the SQL matches the question's
  INTENT — surfaced by putting the generated SQL in the answer + locator.

### Semantic search path (NEW) — `semantic.py`
`doc_search` route. `investigate_doc_search(question, store=None)`: `semantic_search` → keep
hits ≥ SCORE_FLOOR (**0.55, MEASURED** on the real corpus: on-topic ≥0.72, off-topic ≤0.40) →
ONE RELATIONSHIP claim bound to N DOCUMENT/CONTEXTUAL evidences → verify. Below the floor →
INSUFFICIENT_EVIDENCE (semantic analogue of RC-06). **Option-A RAG: vectors RETRIEVE,
deterministic code REPORTS (doc ids + snippets + scores), the model does NOT synthesize** (no
hallucination surface). `is_doc_search_question(q)` requires a doc-content signal and NO SH-
code (a specific shipment → RC-07). Needs the Qdrant index; refuses cleanly if absent.

### The investigations (one module each)
`rc07.py`+`planner.py` (RC-07 + RC-06), `rc02.py`, `rc04.py`, `rc05.py`, `rc01.py`, `rc03.py`,
`rc_ranking.py`, **`analytical.py` (text-to-SQL)**, **`semantic.py` (doc_search)**.

### The router — `router.py` (the single entry point)
`investigate(llm_call, database_url, document_root, question)`. Types: shipment / supplier /
impact / port / warehouse / carrier / **analytical** / **doc_search** / out_of_scope.
Unambiguous entity code (SH-/WH-/CR-) beats the LLM. Precedence in `classify()` (order matters):
impact guard → **doc_search (content question, no SH-code)** → **analytical (aggregate/count
the scenarios don't own; wins over strong-entity for counts, e.g. "how many shipments used
CR3" routes analytical NOT carrier; but "average delay for S07" stays supplier)** → strong
pattern → deterministic → LLM. Entity-validation refusal and the supplier fork (named→RC-02 /
ranking language→ranking / else refuse) are preserved. The analytical + doc_search routes were
added via `patch_router.py` + `patch_semantic_route.py` (guarded, idempotent, in the repo).

### LLM adapter — `ollama_llm.py`
`ollama_call(system, user)` → llama3.2:3b (generation). Judge uses mistral. Embeddings via
nomic-embed-text (Ollama) for Qdrant.

---

## 3. The evaluation layer
- **Objective harness** — `evaluate.py` + `evaluation/eval_questions.json` (**14 dev** Q: the
  original 10 + 4 analytical). Latest: routing 14/14, outcome 14/14, verification 10/10.
- **Held-out** — `evaluation/heldout_questions.json` (**11** Q: original 9 + 2 analytical,
  incl. the CR3 count-vs-scenario precedence boundary). Latest: 11/11, 11/11, 8/8. Entries
  carry `hard_because`. NOTE: analytical eval cases run the LLM's OWN SQL end-to-end, so they
  depend on llama3.2 drafting correctly (de-risked via few-shot; each fix was measured 0/5→5/5).
- **LLM-as-judge** — `llm_judge.py` (CONTROL-GATED). `python evaluate.py --judge`.

---

## 4. The interfaces
- **Streamlit UI** — `app.py` → http://localhost:8501.
- **Grafana** — reads the Postgres `runs` table (`run_logger.py`, surrogate BIGSERIAL). 4 panels.

---

## 5. Test suite — `rc07_vertical_slice/tests/` — **156 tests, all passing**
Original scenario/verifier/router tests (47) PLUS this session's additions:
- `test_sql_guardrail.py` (33) — adversarial battery (parse-don't-regex, allowlist, limit).
- `test_analytical_draft.py` (11) — drafting pipeline (mock LLM).
- `test_analytical.py` (27) — scalar + grouped investigation, per-row mutation, router predicate.
- `test_analytical_router.py` (14) — analytical precedence, no scenario theft, dispatch.
- `test_qdrant_store.py` (6) — exact-lookup parity vs JSON oracle, RC-06 empty, substring-fix, semantic rank.
- `test_document_retrieval.py` (3) — backend switch + safe fallback.
- `test_semantic.py` (15) — doc_search predicate, RELATIONSHIP claim, floor refusal, calibration, routing.
Run: `cd rc07_vertical_slice && python -m pytest tests/ -q` → **156 passed**. Hermetic (mocks
the DB; fake embedders; no Ollama/Postgres/Qdrant server needed). VERIFIED green from a clean clone.

---

## 6. File layout (repo root = ~/supply-chain-intelligence)

    supply-chain-intelligence/
    |-- README.md
    |-- 00_HANDOFF_README.md ... 03_START_HERE_NEXT_SESSION.md   # handoff docs (commit these!)
    |-- requirements.txt            # includes sqlglot, qdrant-client
    |-- .gitignore                  # includes rc07_vertical_slice/qdrant_data/
    |-- datagen/                    # generator + data layer (unchanged this session)
    |-- rc07_vertical_slice/        # the WHOLE agent
    |   |-- agent_contract.py, verifier.py
    |   |-- postgres_tool.py, document_store.py, document_retrieval.py, qdrant_store.py, graph_tool.py
    |   |-- planner.py, rc07.py, rc02.py, rc04.py, rc05.py, rc01.py, rc03.py, rc_ranking.py
    |   |-- sql_guardrail.py, sql_executor.py, analytical_draft.py, analytical.py   # text-to-SQL
    |   |-- semantic.py                                                             # doc_search
    |   |-- build_qdrant_index.py, parity_doc_backends.py                           # qdrant tooling
    |   |-- attack_guardrail.py                                                     # adversarial demo
    |   |-- patch_router.py, patch_verifier.py, patch_document_retrieval.py, patch_semantic_route.py
    |   |-- ollama_llm.py, llm_judge.py, run_logger.py, evaluate.py, app.py
    |   |-- router.py
    |   |-- evaluation/ (eval_questions.json [14], heldout_questions.json [11])
    |   |-- fixtures/, tests/ (18 test files, 156 tests)
    |   |-- qdrant_data/            # GENERATED vector index (git-ignored)
    |-- artifacts/documents/        # generated (git-ignored)

The patch_*.py scripts have already been applied to the live files (their edits are committed).
They remain in the repo as an audit trail / idempotent re-appliers.
