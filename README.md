# Supply Chain Intelligence Platform

An agentic AI platform that investigates operational supply-chain problems — "what happened to this shipment?", "why is this supplier chronically late?", "which customers does a port disruption cascade to?" — by autonomously querying a SQL database, searching operational documents, and traversing a graph, then returns verified, source-cited answers and refuses to guess when the evidence is insufficient.

Runs fully locally and free using Ollama — no API keys, no cloud cost.

Status: a multi-capability agent spanning three data sources (SQL, documents, graph) runs end-to-end on real generated data, with a self-validating evaluation harness, an interactive UI, and an observability dashboard. 47 automated tests.

## Why this project is different

Anyone can wire an LLM to a database. Three things set this apart:

1. A synthetic world with planted, separable causes. A deterministic generator builds a fictional freight-distribution company (~23,000 rows in PostgreSQL, ~2,700 correlated documents, ~11,900 graph nodes) containing known root-cause scenarios. Because the answers are planted, accuracy can be measured against ground truth. The causal levers are hidden from the schema the agent sees, so the agent must investigate rather than look up the answer.

2. The LLM plans; deterministic code controls the evidence. The agent uses a local LLM to route questions and choose tools, but never to write facts. Evidence is assembled deterministically and gated by a hardened, mutation-tested verifier: numeric and comparative figures must match their SQL evidence, causal claims need documentary support, and graph claims must bind to graph evidence — or the answer is downgraded.

3. It is measured, not asserted — and the measurement self-validates. An objective harness scores routing, outcome, and verification accuracy against ground truth. A held-out set tests generalization. An LLM-as-judge scores faithfulness, but only after passing a control test that proves, each run, that it can catch a deliberately-corrupted answer — otherwise the faithfulness score is withheld as untrustworthy.

## What it does

A single entry point classifies the question and dispatches to the right investigation across three data sources:

- "What happened to shipment SH-6968?" -> SQL + document retrieval -> SUPPORTED, cites the real incident report.
- "Why is supplier S07 chronically late?" -> three SQL queries, a de-confounded comparison -> SUPPORTED, with an honest comparative claim.
- "Which supplier is the worst?" -> ranks all suppliers by de-confounded clean-route delay -> SUPPORTED, names the worst (S07) with its margin over the field, noting that ranking by raw delay would unfairly blame suppliers for their routing.
- "Which customers are affected by port congestion through shared routes?" -> graph traversal -> SUPPORTED, finds the co-exposure network.
- "What is the capital of France?" -> out of scope -> refuses instead of guessing.

The supplier answer shows the epistemics: the verified claim is the de-confounded COMPARATIVE fact (S07 averages 5.27 days on clean routes vs 1.0 for peers, a 4.27-day gap with the congested-port factor removed); the causal reading stays as careful prose ("strongly indicates", not "proves").

The graph answer is the one SQL cannot produce cleanly: "Congestion at PORT-GEN does not hit one supplier in isolation. 21 customers are co-exposed on route RT-04: each is served by more than one of the suppliers S07, S11, S19, S23, which all pass through PORT-GEN." That is a multi-hop traversal across shared nodes — the reason the graph exists.

## Interfaces

Two front-ends make the system usable and legible:

- Streamlit UI — type a question and watch the investigation unfold: the tool-call trace (SQL / documents / graph), the outcome badge, the answer, the evidence it is bound to, and the verification checks. It makes the thing most "chat with your data" demos hide — the verified reasoning path — the centrepiece. `streamlit run app.py`
- Grafana observability dashboard — every agent run is logged to a Postgres `runs` table; a Grafana dashboard reads it for monitoring: outcome breakdown, investigation-type distribution, verification pass rate, and average latency by investigation type (which visibly shows shipment investigations cost more, because they query SQL and search documents, while others hit a single source).

The distinction is deliberate: Streamlit is the interaction surface; Grafana is the observability layer over the run history.

## Architecture

- PostgreSQL — structured business data, the source of truth. Hidden causal levers stripped from the schema. Also holds the agent `runs` log.
- Neo4j — a graph projection built FROM Postgres (11,863 nodes, 23,770 relationships), for multi-hop co-exposure questions. Never an independent source of truth.
- Document store — ~2,700 documents generated from the structured events (skeleton -> text -> validated), so they corroborate the data.
- Router — classifies a question (shipment / supplier / impact / port / warehouse / carrier / out-of-scope) via the LLM with a deterministic fallback; an unambiguous entity code (SH-/WH-/CR-) beats the LLM's guess. Dispatches and logs every run.
- Verifier — mutation-tested checks (numeric, comparative, causal, trace, partial) gate every claim.
- Evaluation — objective scoreboard + held-out set + control-gated LLM-as-judge.
- Interfaces — Streamlit UI (interaction) + Grafana dashboard (observability).

## Tech stack

Python, PostgreSQL, Neo4j, LangGraph, Ollama (llama3.2, mistral), Pydantic, SQLAlchemy, pytest, Streamlit, Grafana.

## Quickstart

Requires WSL/Linux, Python 3.11+, PostgreSQL, Neo4j, Ollama (and Grafana for the dashboard).

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
ollama pull llama3.2:3b

export DATABASE_URL="postgresql://USER:PASSWORD@localhost:5432/meridian"

# generate the world: Postgres + documents
python -m datagen.run --persist --docs

# build the graph projection from Postgres
python -c "from datagen.run import generate; from datagen.graph_projection import project_graph; project_graph(generate())"

cd rc07_vertical_slice

# tests + evaluation
python -m pytest tests/ -q            # 47 tests
python evaluate.py                    # objective scoreboard
python evaluate.py --judge            # + control-gated faithfulness
EVAL_FILE=evaluation/heldout_questions.json python evaluate.py   # held-out set

# interactive UI
streamlit run app.py                  # http://localhost:8501

# observability: runs are logged to a Postgres 'runs' table;
# point a Grafana PostgreSQL datasource at the meridian DB and build panels over it.
```

## The planted scenarios

Seven root-cause stories with known answers, chosen to exercise different failure modes:

| ID | Story | Tests | Agent status |
|----|-------|-------|--------------|
| RC-01 | Port congestion in Q1 | seasonal pattern detection | live (SQL) |
| RC-02 | Supplier chronically late | de-confounding supplier from route | live (SQL) |
| RC-03 | Carrier degrading over time | trend vs single-cause | live (SQL, PARTIAL verdict) |
| RC-04 | Warehouse capacity bottleneck | stage localization (a trap) | live (SQL) |
| RC-05 | Shared-route co-exposure | multi-hop graph traversal | live (graph) |
| RC-06 | Unexplained delay | honest refusal | live (SQL+docs) |
| RC-07 | Isolated customs hold | precise single-entity retrieval | live (SQL+docs) |

## Measured results

Scored against planted ground truth:

- Dev eval set (10 questions, all 7 scenarios): routing 100%, outcome 100%, verification 100%.
- Held-out set (9 questions, fresh phrasing, all 7 scenarios): routing 100%, outcome 100%, verification 100%. Includes a case that honestly refuses because refusing is correct (a question naming a port that does not exist), and the open-ended "which supplier is worst" — once a documented-boundary refusal, now answered by the ranking capability it motivated.
- Faithfulness (control-gated LLM judge): 1.00, reported only because the judge passed its control (scored a corrupted answer 0.0) that run.

## Engineering notes (measured, not claimed)

- Every planted signal is verified in the data — e.g. the chronically-late supplier shows a 4.27-day gap over peers on clean routes.
- The verifier is mutation-tested: each check fails when the code it guards is deliberately broken.
- The LLM judge caught a real bug — the agent asserting a cause ("customs hold") that contradicted its own retrieved document ("carrier delay"). Fixed by deriving the answer's cause from the evidence. The judge's own control test then caught the judge being too lenient; the judge prompt was hardened until the control passed.
- The graph query was scoped honestly: an initial traversal showed all 30 suppliers use the route (a weak story); the real co-exposure question is scoped to the known problem-network, where 21 customers are genuinely co-exposed.
- Bugs caught by testing each layer before the next sits on it: a cross-scenario data collision; a schema-rebuild idempotency bug; an evidence-phrasing mismatch that silently downgraded correct answers; a small-model routing loop; a comparative-check false rejection of a valid derived figure; and a run-logging key collision that silently dropped most runs until the log was keyed by a surrogate id.

## Project status

Built and verified:
- Deterministic generator (8 stages, ~23k rows, ~2,700 documents, reproducible)
- PostgreSQL (hidden-lever strip) + Neo4j graph projection + document pipeline
- Agent output contract + hardened, mutation-tested verifier
- Multi-capability router across three data sources (SQL, documents, graph) + refusal
- Seven live investigations (all scenarios: RC-01 through RC-07)
- Self-validating evaluation: objective + held-out + control-gated LLM judge
- Streamlit interactive UI + Grafana observability dashboard
- 47 automated tests

In progress / planned:
- Held-out eval coverage for the four newly-live scenarios
- Text-to-SQL for open-ended queries

## License

MIT
