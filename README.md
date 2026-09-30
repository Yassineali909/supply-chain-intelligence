# Supply Chain Intelligence Platform

An agentic AI platform that investigates operational supply-chain problems — "what happened to this shipment?", "why is this supplier chronically late?" — by autonomously querying a SQL database and searching operational documents, then returns verified, source-cited answers and refuses to guess when the evidence is insufficient.

Runs fully locally and free using Ollama — no API keys, no cloud cost.

Status: active portfolio project. The synthetic-data foundation and the first agent investigation slice (RC-07) are complete, tested, and verified end-to-end. The document pipeline, graph traversal, and additional investigation scenarios are in progress.

## Why this project is different

Anyone can wire an LLM to a database. Two things set this apart:

1. A synthetic world with planted, separable causes. A deterministic generator builds a fictional freight-distribution company (~23,000 rows in PostgreSQL) containing known root-cause scenarios — a chronically-late supplier, seasonal port congestion, a degrading carrier, a downstream-warehouse bottleneck, and a deliberately unexplained delay. Because the answers are planted, retrieval and reasoning quality can be measured against ground truth. The causal levers are hidden from the schema the agent sees, so the agent must investigate the delays rather than look up the answer.

2. The LLM plans; deterministic code controls the evidence. The agent uses a local LLM to decide which tools to call, but never to write facts. Evidence is assembled deterministically and gated by a hardened verifier: every claim must bind to evidence a tool produced, numeric claims must match their SQL evidence, and a causal claim needs direct documentary support — or the answer is downgraded.

## What it does

Given a question, the agent runs an investigation loop: it decides whether to query the database, observes the shipment record, decides whether to search documents, observes the incident report, verifies that every claim is bound to real evidence, and returns SUPPORTED / PARTIALLY_SUPPORTED / INSUFFICIENT_EVIDENCE with cited evidence.

Example — "What happened to shipment SH-4921?":

outcome: SUPPORTED
verification: PASSED
tools: query_database -> search_documents -> verify_evidence
answer: Shipment SH-4921 arrived 10 days late. The incident report
attributes the delay to a customs hold.


When the evidence is not there, it refuses instead of inventing a cause:

outcome: INSUFFICIENT_EVIDENCE
answer: Shipment X was delayed by N days, but I could not find a document
that establishes why.


## Architecture

- PostgreSQL — structured business data (suppliers, orders, shipments, deliveries, incidents), the source of truth. Hidden causal levers stripped from the schema.
- Deterministic generator — produces correlated data and documents from a single seed; fully reproducible.
- (Planned) Neo4j — multi-hop impact questions.
- (Planned) Qdrant — semantic document search.

The agent: an LLM planner (llama3.2 via Ollama) chooses tools, deterministic code assembles evidence, and a hardened verifier gates every claim.

## Tech stack

Python, PostgreSQL, LangGraph, Ollama (llama3.2, mistral), Pydantic, SQLAlchemy, pytest. Planned: Neo4j, Qdrant.

## Quickstart

Requires WSL/Linux, Python 3.11+, PostgreSQL, and Ollama.

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
ollama pull llama3.2:3b
export DATABASE_URL="postgresql://USER:PASSWORD@localhost:5432/meridian"
python -m datagen.run --persist
cd rc07_vertical_slice && python -m pytest tests/ -q
```

## The planted scenarios

Seven root-cause stories with known answers, chosen to exercise different failure modes:

| ID | Story | Tests | Expected outcome |
|----|-------|-------|------------------|
| RC-01 | Port congestion in Q1 | seasonal pattern detection | Supported |
| RC-02 | Supplier chronically late | de-confounding supplier from route | Supported |
| RC-03 | Carrier degrading over time | trend vs single-cause | Partially supported |
| RC-04 | Warehouse capacity bottleneck | stage localization (a trap) | Supported |
| RC-05 | Shared-route co-exposure | multi-hop graph traversal | Supported |
| RC-06 | Unexplained delay | honest refusal | Insufficient evidence |
| RC-07 | Isolated customs hold | precise single-entity retrieval | Supported |

RC-02 is de-confounded so the supplier's effect is measurable independently of the congested route it also uses. RC-04 is a trap: the delay is downstream at the warehouse while the inbound shipment arrived on time, so a naive agent blames the supplier and is wrong. RC-06 has no explanatory document — the correct answer is a refusal.

## Engineering notes (measured, not claimed)

- Every planted signal is verified in the data — e.g. the chronically-late supplier shows a ~4-day delay over peers on clean routes, isolating the supplier effect from the port effect.
- The verifier is mutation-tested: each check was confirmed to fail when the code it guards is deliberately broken.
- Bugs caught by testing each layer before the next sits on it: a cross-scenario data collision that would have corrupted the refusal test; a schema-rebuild idempotency bug; an evidence-phrasing mismatch that silently downgraded correct answers; and a small-model routing loop, fixed by constraining the agent's action space.

## Project status

Built and verified:
- Deterministic generator (8 stages, ~23k rows, 16 tables, reproducible)
- Seven planted root-cause scenarios with verified signals
- PostgreSQL persistence with hidden-lever strip
- Agent output contract + hardened, mutation-tested verifier
- LLM-planned investigation loop (RC-07), robust to small-model misbehaviour
- 15 automated tests

In progress / planned:
- Document generation pipeline (structured -> prose -> validated -> indexed)
- Qdrant semantic document search
- Neo4j graph projection for multi-hop questions
- Text-to-SQL for open-ended queries
- Multi-source investigation slices and the evaluation/ablation harness
- Lightweight UI showing the agent's tool-call trace

## License

MIT
