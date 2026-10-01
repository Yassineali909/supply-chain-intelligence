# Supply Chain Intelligence Platform

An agentic AI platform that investigates operational supply-chain problems — "what happened to this shipment?", "why is this supplier chronically late?" — by autonomously querying a SQL database and searching operational documents, then returns verified, source-cited answers and refuses to guess when the evidence is insufficient.

Runs fully locally and free using Ollama — no API keys, no cloud cost.

Status: active portfolio project. A multi-capability agent (two investigation types + out-of-scope refusal) runs end-to-end on real generated data, with an objective evaluation harness. Graph traversal, LLM-judged quality scoring, and additional scenarios are in progress.

## Why this project is different

Anyone can wire an LLM to a database. Three things set this apart:

1. A synthetic world with planted, separable causes. A deterministic generator builds a fictional freight-distribution company (~23,000 rows in PostgreSQL, ~2,700 correlated documents) containing known root-cause scenarios — a chronically-late supplier, seasonal port congestion, a degrading carrier, a downstream-warehouse bottleneck, and a deliberately unexplained delay. Because the answers are planted, accuracy can be measured against ground truth. The causal levers are hidden from the schema the agent sees, so the agent must investigate the delays rather than look up the answer.

2. The LLM plans; deterministic code controls the evidence. The agent uses a local LLM to decide which tools to call and how to route a question, but never to write facts. Evidence is assembled deterministically and gated by a hardened, mutation-tested verifier: every claim must bind to evidence a tool produced, numeric and comparative figures must match their SQL evidence, and a causal claim needs direct documentary support — or the answer is downgraded.

3. It is measured, not asserted. An objective evaluation harness scores routing accuracy, outcome accuracy, and verification integrity against planted ground truth. A separate held-out set with fresh phrasing tests generalization — and surfaced a real scope boundary (documented below) rather than a polished 100%.

## What it does

A single entry point classifies the question and dispatches to the right investigation:

- "What happened to shipment SH-6968?" -> shipment investigation (SQL + documents) -> SUPPORTED, cites the real incident report.
- "Why is supplier S07 chronically late?" -> supplier investigation (three SQL queries, de-confounded comparison) -> SUPPORTED, with an honest comparative claim.
- "What is the capital of France?" -> out of scope -> refuses instead of guessing.

Example — the supplier investigation's answer:

```
Supplier S07 is chronically late: it averages 5.59 days of delay overall. Critically,
the lateness persists on clean routes that avoid the congested port (5.27 days vs 1.0
days for peers on the same routes, a 4.27-day gap). Because the gap remains once the
congested-port factor is removed, this strongly indicates the supplier itself, not its
routing, is the source of the delays.
```

Note the epistemics: the verified claim is the COMPARATIVE fact (the de-confounded gap); the causal reading stays as careful prose ("strongly indicates", not "proves"), because observational data with one confounder controlled is not proof of causation.

## Architecture

- PostgreSQL — structured business data (suppliers, orders, shipments, deliveries, incidents), the source of truth. Hidden causal levers stripped from the schema.
- Deterministic generator — produces correlated data and ~2,700 documents from a single seed; fully reproducible.
- Router — classifies a question (shipment / supplier / out-of-scope) via the LLM with a deterministic entity-pattern fallback, then dispatches.
- Investigations — RC-07 (shipment: SQL + document retrieval) and RC-02 (supplier: multi-step de-confounded comparison).
- Verifier — mutation-tested checks gate every claim before the answer is returned.
- Evaluation — objective scoreboard (routing / outcome / verification) against planted ground truth, plus a held-out generalization set.
- (Planned) Neo4j multi-hop traversal; Qdrant semantic search; LLM-as-judge quality layer.

## Tech stack

Python, PostgreSQL, LangGraph, Ollama (llama3.2, mistral), Pydantic, SQLAlchemy, pytest. Planned: Neo4j, Qdrant.

## Quickstart

Requires WSL/Linux, Python 3.11+, PostgreSQL, and Ollama.

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
ollama pull llama3.2:3b
export DATABASE_URL="postgresql://USER:PASSWORD@localhost:5432/meridian"

# generate the world + load Postgres + write documents
python -m datagen.run --persist --docs

# run the agent tests and the evaluation scoreboard
cd rc07_vertical_slice
python -m pytest tests/ -q            # 26 tests
python evaluate.py                    # objective scoreboard
EVAL_FILE=evaluation/heldout_questions.json python evaluate.py   # held-out set
```

## The planted scenarios

Seven root-cause stories with known answers, chosen to exercise different failure modes:

| ID | Story | Tests | Agent status |
|----|-------|-------|--------------|
| RC-01 | Port congestion in Q1 | seasonal pattern detection | data only |
| RC-02 | Supplier chronically late | de-confounding supplier from route | live investigation |
| RC-03 | Carrier degrading over time | trend vs single-cause | data only |
| RC-04 | Warehouse capacity bottleneck | stage localization (a trap) | data only |
| RC-05 | Shared-route co-exposure | multi-hop graph traversal | planned (graph) |
| RC-06 | Unexplained delay | honest refusal | data only |
| RC-07 | Isolated customs hold | precise single-entity retrieval | live investigation |

RC-02 is de-confounded so the supplier's effect is measurable independently of the congested route it also uses. RC-04 is a trap: the delay is downstream at the warehouse while the inbound shipment arrived on time. RC-06 has no explanatory document — the correct answer is a refusal.

## Measured results

Objective scoreboard, scored against planted ground truth:

- Dev eval set (5 questions): routing 100%, outcome 100%, verification integrity 100%.
- Held-out set (5 harder questions, fresh phrasing): routing 100%, outcome 80%.

The one held-out failure is informative, not hidden: "which of our suppliers is the biggest problem?" routes correctly to a supplier investigation, but names no specific supplier to query, so the agent honestly refuses rather than inventing an answer. This is a documented scope boundary — the system investigates named entities; open-ended ranking is a candidate next capability.

## Engineering notes (measured, not claimed)

- Every planted signal is verified in the data — e.g. the chronically-late supplier shows a 4.27-day gap over peers on clean routes (congested port removed).
- The verifier is mutation-tested: each check was confirmed to fail when the code it guards is deliberately broken.
- The agent is robust to a weak local model: routing and tool selection use the LLM but fall back deterministically, and wrong-in-context actions are made structurally unavailable rather than merely discouraged.
- Bugs caught by testing each layer before the next sits on it: a cross-scenario data collision that would have corrupted the refusal test; a schema-rebuild idempotency bug; an evidence-phrasing mismatch that silently downgraded correct answers; a small-model routing loop; and a comparative-claim check that initially rejected a valid derived figure.

## Project status

Built and verified:
- Deterministic generator (8 stages, ~23k rows, 16 tables, ~2,700 documents, reproducible)
- Seven planted root-cause scenarios with verified signals; two live as agent investigations (RC-07, RC-02)
- PostgreSQL persistence with hidden-lever strip; document pipeline (skeleton -> text -> validate)
- Agent output contract + hardened, mutation-tested verifier (numeric, comparative, causal, trace, partial)
- Multi-capability router (shipment / supplier / out-of-scope refusal) on real data
- Objective evaluation harness + held-out generalization set
- 26 automated tests

In progress / planned:
- LLM-as-judge quality layer (faithfulness, answer relevance)
- RC-06 live refusal through the full agent; Neo4j graph for RC-05 multi-hop
- Qdrant semantic document search; text-to-SQL for open-ended queries
- "Find the worst supplier" ranking capability (motivated by the held-out boundary)
- Lightweight UI showing the agent's tool-call trace

## License

MIT
