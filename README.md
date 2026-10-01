# Supply Chain Intelligence Platform

An agentic AI platform that investigates operational supply-chain problems — "what happened to this shipment?", "why is this supplier chronically late?", "which customers does a port disruption cascade to?" — by autonomously querying a SQL database, searching operational documents, and traversing a graph, then returns verified, source-cited answers and refuses to guess when the evidence is insufficient.

Runs fully locally and free using Ollama — no API keys, no cloud cost.

Status: a multi-capability agent spanning three data sources (SQL, documents, graph) runs end-to-end on real generated data, with a self-validating evaluation harness. 29 automated tests.

## Why this project is different

Anyone can wire an LLM to a database. Three things set this apart:

1. A synthetic world with planted, separable causes. A deterministic generator builds a fictional freight-distribution company (~23,000 rows in PostgreSQL, ~2,700 correlated documents, ~11,900 graph nodes) containing known root-cause scenarios. Because the answers are planted, accuracy can be measured against ground truth. The causal levers are hidden from the schema the agent sees, so the agent must investigate rather than look up the answer.

2. The LLM plans; deterministic code controls the evidence. The agent uses a local LLM to route questions and choose tools, but never to write facts. Evidence is assembled deterministically and gated by a hardened, mutation-tested verifier: numeric and comparative figures must match their SQL evidence, causal claims need documentary support, and graph claims must bind to graph evidence — or the answer is downgraded.

3. It is measured, not asserted — and the measurement self-validates. An objective harness scores routing, outcome, and verification accuracy against ground truth. A held-out set tests generalization. An LLM-as-judge scores faithfulness, but only after passing a control test that proves, each run, that it can catch a deliberately-corrupted answer — otherwise the faithfulness score is withheld as untrustworthy.

## What it does

A single entry point classifies the question and dispatches to the right investigation across three data sources:

- "What happened to shipment SH-6968?" -> SQL + document retrieval -> SUPPORTED, cites the real incident report.
- "Why is supplier S07 chronically late?" -> three SQL queries, a de-confounded comparison -> SUPPORTED, with an honest comparative claim.
- "Which customers are affected by port congestion through shared routes?" -> graph traversal -> SUPPORTED, finds the co-exposure network.
- "What is the capital of France?" -> out of scope -> refuses instead of guessing.

The supplier answer shows the epistemics: the verified claim is the de-confounded COMPARATIVE fact (S07 averages 5.27 days on clean routes vs 1.0 for peers, a 4.27-day gap with the congested-port factor removed); the causal reading stays as careful prose ("strongly indicates", not "proves"), because observational data with one confounder controlled is not proof of causation.

The graph answer is the one SQL cannot produce cleanly: "Congestion at PORT-GEN does not hit one supplier in isolation. 21 customers are co-exposed on route RT-04: each is served by more than one of the suppliers S07, S11, S19, S23, which all pass through PORT-GEN. A disruption there cascades to those customers through multiple suppliers at once." That is a multi-hop traversal across shared nodes — the reason the graph exists.

## Architecture

- PostgreSQL — structured business data, the source of truth. Hidden causal levers stripped from the schema.
- Neo4j — a graph projection built FROM Postgres (11,863 nodes, 23,770 relationships), for multi-hop co-exposure questions. Never an independent source of truth.
- Document store — ~2,700 documents generated from the structured events (skeleton -> text -> validated), so they corroborate the data.
- Router — classifies a question (shipment / supplier / impact / out-of-scope) via the LLM with a deterministic fallback, then dispatches.
- Verifier — mutation-tested checks (numeric, comparative, causal, trace, partial) gate every claim.
- Evaluation — objective scoreboard + held-out set + control-gated LLM-as-judge.

## Tech stack

Python, PostgreSQL, Neo4j, LangGraph, Ollama (llama3.2, mistral), Pydantic, SQLAlchemy, pytest.

## Quickstart

Requires WSL/Linux, Python 3.11+, PostgreSQL, Neo4j, and Ollama.

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
ollama pull llama3.2:3b
export DATABASE_URL="postgresql://USER:PASSWORD@localhost:5432/meridian"

# generate the world: Postgres + documents
python -m datagen.run --persist --docs

# build the graph projection from Postgres
python -c "from datagen.run import generate; from datagen.graph_projection import project_graph; project_graph(generate())"

# run tests + the evaluation scoreboard
cd rc07_vertical_slice
python -m pytest tests/ -q            # 29 tests
python evaluate.py                    # objective scoreboard
python evaluate.py --judge            # + control-gated faithfulness
EVAL_FILE=evaluation/heldout_questions.json python evaluate.py   # held-out set
```

## The planted scenarios

Seven root-cause stories with known answers, chosen to exercise different failure modes:

| ID | Story | Tests | Agent status |
|----|-------|-------|--------------|
| RC-01 | Port congestion in Q1 | seasonal pattern detection | data only |
| RC-02 | Supplier chronically late | de-confounding supplier from route | live (SQL) |
| RC-03 | Carrier degrading over time | trend vs single-cause | data only |
| RC-04 | Warehouse capacity bottleneck | stage localization (a trap) | data only |
| RC-05 | Shared-route co-exposure | multi-hop graph traversal | live (graph) |
| RC-06 | Unexplained delay | honest refusal | data only |
| RC-07 | Isolated customs hold | precise single-entity retrieval | live (SQL+docs) |

## Measured results

Scored against planted ground truth:

- Dev eval set (5 questions): routing 100%, outcome 100%, verification 100%.
- Held-out set (5 harder questions, fresh phrasing): routing 100%, outcome 80% — the one miss is a documented scope boundary (an open-ended "which supplier is worst" routes correctly but names no entity to query, so the agent honestly refuses).
- Faithfulness (control-gated LLM judge): 1.00, reported only because the judge passed its control (scored a corrupted answer 0.0) that run.

## Engineering notes (measured, not claimed)

- Every planted signal is verified in the data — e.g. the chronically-late supplier shows a 4.27-day gap over peers on clean routes.
- The verifier is mutation-tested: each check fails when the code it guards is deliberately broken.
- The LLM judge caught a real bug — the agent asserting a cause ("customs hold") that contradicted its own retrieved document ("carrier delay"). Fixed by deriving the answer's cause from the evidence. The judge's own control test then caught the judge being too lenient; the judge prompt was hardened until the control passed.
- The graph query was scoped honestly: an initial traversal showed all 30 suppliers use the route (a weak story); the real co-exposure question is scoped to the known problem-network, where 21 customers are genuinely co-exposed.
- Bugs caught by testing each layer before the next sits on it: a cross-scenario data collision; a schema-rebuild idempotency bug; an evidence-phrasing mismatch that silently downgraded correct answers; a small-model routing loop (fixed by constraining the action space); a comparative-check false rejection of a valid derived figure.

## Project status

Built and verified:
- Deterministic generator (8 stages, ~23k rows, ~2,700 documents, reproducible)
- PostgreSQL (hidden-lever strip) + Neo4j graph projection + document pipeline
- Agent output contract + hardened, mutation-tested verifier
- Multi-capability router across three data sources (SQL, documents, graph) + refusal
- Three live investigations (RC-07, RC-02, RC-05)
- Self-validating evaluation: objective + held-out + control-gated LLM judge
- 29 automated tests

In progress / planned:
- RC-06 live refusal through the full agent
- "Find the worst supplier" ranking capability (motivated by the held-out boundary)
- Lightweight UI showing the agent's tool-call trace
- Text-to-SQL for open-ended queries

## License

MIT
