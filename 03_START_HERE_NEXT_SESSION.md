# START HERE — NEXT SESSION

Read 00 → 01 → 02 first. Then follow this. **Step 1 is to CONFIRM state** — these docs were
written from the previous session's knowledge; verify the numbers against the live repo and
trust the repo if they disagree (then update these docs).

---

## 1. CONFIRM STATE FIRST (don't trust these docs blindly)

```bash
cd ~/supply-chain-intelligence
git --no-pager log --oneline -12          # should show the text-to-SQL + qdrant + semantic commits
git status -s -b                          # expect clean, up to date with origin/main
cd rc07_vertical_slice && python -m pytest tests/ -q | tail -1   # EXPECT: 156 passed
python -c "import json; print('dev', len(json.load(open('evaluation/eval_questions.json'))), '| heldout', len(json.load(open('evaluation/heldout_questions.json'))))"   # EXPECT: dev 14 | heldout 11
```

If the test count isn't 156 or git isn't clean, STOP and reconcile before building (B19/B20:
a green/flat count can hide a gap). Also verify a CLEAN CLONE builds if you touched committed
files last time: `cd /tmp && rm -rf vc && git clone -q <repo> vc && cd vc/rc07_vertical_slice && python -m pytest tests/ -q | tail -1`.

---

## 2. Bring the environment up (WSL does NOT persist services across restarts)

```bash
sudo service postgresql start && sudo pg_ctlcluster 18 main start
sudo service neo4j start && sleep 10
sudo service grafana-server start           # only if you want the dashboard
ollama list                                 # need: llama3.2:3b, mistral, nomic-embed-text
# if missing: ollama pull nomic-embed-text   (~274MB, 768-dim — required for Qdrant embedder)

cd ~/supply-chain-intelligence && source venv/bin/activate
which python                                # must point into venv/bin/python
pip show sqlglot qdrant-client >/dev/null 2>&1 || pip install sqlglot qdrant-client
```

Credentials (local dev, throwaway):
- Postgres: `postgresql://yassine:devpass@localhost:5432/meridian`
  (SQLAlchemy/psycopg URL: `postgresql+psycopg://yassine:devpass@localhost:5432/meridian`)
- Neo4j: `bolt://localhost:7687`, user `neo4j`, password `devpass123`
- Grafana: http://localhost:3000
Environment: WSL (Ubuntu) + VS Code, Python 3.14.

---

## 3. Rebuild data / vector index if needed

```bash
cd ~/supply-chain-intelligence
python -m datagen.run --persist --docs
python -c "from datagen.run import generate; from datagen.graph_projection import project_graph; project_graph(generate())"
# vector index (needed for USE_QDRANT exact-lookup AND the doc_search semantic route):
cd rc07_vertical_slice && python build_qdrant_index.py     # embeds 2746 docs -> ./qdrant_data; prints PARITY GATE
```
Expected: ~23,256 rows / 16 tables; ~2746 docs; ~11,863 nodes / ~23,770 rels; 2746 vectors;
PARITY GATE: PASS (exact lookup == JSON 15/15; all 5 RC-06 shipments empty in both).

---

## 4. Confirm the system works (live)

```bash
cd ~/supply-chain-intelligence/rc07_vertical_slice
python -m pytest tests/ -q                   # 156 passed
python evaluate.py                           # dev: routing 14/14, outcome 14/14, verify 10/10
EVAL_FILE=evaluation/heldout_questions.json python evaluate.py   # held-out: 11/11, 11/11, 8/8
python sql_executor.py                       # Layer 1/4: bypassed write rejected + timeout aborts
# a text-to-SQL run (scalar):
python -c "from router import investigate; from ollama_llm import ollama_call; r=investigate(ollama_call,'postgresql+psycopg://yassine:devpass@localhost:5432/meridian','../artifacts/documents','how many shipments used CR3?'); print(r.outcome.value); print(r.answer[:200])"
# a grouped run:
python -c "from router import investigate; from ollama_llm import ollama_call; r=investigate(ollama_call,'postgresql+psycopg://yassine:devpass@localhost:5432/meridian','../artifacts/documents','what is the average delay per carrier?'); print(r.outcome.value); print(r.answer[:300])"
# semantic doc_search (SUPPORTED) + its honest refusal:
python -c "from router import investigate; from ollama_llm import ollama_call; print(investigate(ollama_call,'postgresql+psycopg://yassine:devpass@localhost:5432/meridian','../artifacts/documents','what do our documents say about customs holds?').outcome.value)"
python -c "from router import investigate; from ollama_llm import ollama_call; print(investigate(ollama_call,'postgresql+psycopg://yassine:devpass@localhost:5432/meridian','../artifacts/documents','what do our documents say about quantum computing?').outcome.value)"   # EXPECT INSUFFICIENT_EVIDENCE
streamlit run app.py                         # http://localhost:8501
```

---

## 5. EXACT CURRENT STATE (as of end of the text-to-SQL + Qdrant session)
- 7 scenarios + ranking + **text-to-SQL (scalar + grouped)** + **semantic doc_search** = LIVE.
- Routes: shipment / supplier / impact / port / warehouse / carrier / analytical / doc_search / out_of_scope.
- 156 tests. Dev 14/14, held-out 11/11. Verified green from a clean clone. All committed + pushed.
- Qdrant WIRED behind `USE_QDRANT=1` (exact lookup, RC-06-preserving, parity-proven live);
  `doc_search` semantic route LIVE (floor 0.55, measured). Claim type **AGGREGATE** added.
- Latest commits (capabilities, newest-ish first): semantic doc_search route; wire Qdrant via
  document_retrieval; Qdrant store + parity gate; AGGREGATE type + verifier check + analytical
  router route; multi-row grouped; few-shot hardening (CR3 + per/by, each 0/5→5/5); eval
  analytical cases; LLM drafting; layered SQL guardrail.

---

## 6. STILL OPEN (quick, mostly mine — do these early)
1. **Confirm the 16-table allowlist.** `psql "$PGURL" -c "\dt"` → fill ALL 16 into
   `BUSINESS_TABLES` in `sql_guardrail.py` (currently 14 of 16). Exclude the `runs` log table.
2. Production-grade read-only: a dedicated SELECT-only Postgres role instead of
   `SET TRANSACTION READ ONLY` (documented in `sql_executor.py`). Nice-to-have.

---

## 7. PRIORITIZED NEXT BUILD CANDIDATES (the next session's choice)
1. **Grounded-LLM-summary for doc_search** — let the model synthesize an answer from the
   retrieved docs. BUT this needs its OWN hallucination verifier (check every summary claim is
   grounded in retrieved text). DO NOT ship the summary without that check — it's the exact RAG
   hole D22 avoided. This is real design + a mini-verifier; a strong fresh-head build.
2. **Semantic search in the Streamlit UI** — surface the doc_search route + scores in `app.py`.
   High demo value, low risk.
3. **Docker Compose one-command stack** — Postgres + Neo4j + Qdrant + Ollama + app. FIRST:
   `apt remove` the snap docker (it's broken in WSL — no daemon), install `docker.io` or Docker
   Desktop with WSL integration. Then wire the stack. High "can you ship it" value.
4. **Demo video** (Streamlit + Grafana + a few live questions incl. an honest refusal) —
   highest-value NON-code task; shows the whole thing working.
5. **Multi-row analytical v2** — 3+ column results, numeric-label time-series beyond 2 columns.

---

## 8. HOW TO WORK (match the user's rigor — this is the actual skill on display)
Verify the deterministic layer before the stochastic one. Prove the red (mutation-test any new
check). Measure, don't guess (thresholds from real distributions, then lock with a test — B21).
Refuse rather than overclaim; surface residual risk (D18, D22). Vertical-slice (no feature
without a failing case). Safe scripted patches: assert each anchor matches EXACTLY ONCE and the
replacement is NOT already present; apply in-memory; write only if all pass; keep patch_*.py in
the repo. Commit per unit; watch `git status` for strays; and — the big one — **"done" means
green FROM A CLEAN CLONE and a confirmed test count, never a local green alone** (B19/B20). When
a run looks perfect, run the FAILURE case on purpose too (B21). venv + WSL services after every
restart. Keep these four handoff docs current — they are why a fresh session starts at full speed.
