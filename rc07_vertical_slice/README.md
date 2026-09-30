# RC-07 Vertical Slice

First agent-phase slice for the MeridianFreight Supply Chain Intelligence project.

Goal:

> `What happened to shipment SH-4921?`

This slice implements the smallest end-to-end investigation loop supported by the v1
agent output contract:

```text
question
  -> identify shipment
  -> query_database
  -> search_documents
  -> verify_evidence
  -> AgentResponse
```

It deliberately does **not** implement Neo4j, Text-to-SQL generation, Qdrant, or a UI.
Those are downstream capabilities and should be added only when a failing vertical slice
requires them.

## Verifier hardening status

The verifier is now the deterministic regression floor for the agent phase. It enforces:

1. claims must bind to real evidence IDs;
2. bound evidence must be produced by a successful **non-verification** tool;
3. numeric RC-07 claims must match the delay value in SQL evidence exactly;
4. `SUPPORTED` causal claims require at least one `DIRECT` documentary source;
5. `CONTEXTUAL` evidence cannot establish a specific causal claim;
6. a legitimate `PARTIALLY_SUPPORTED` response must explicitly contain a `PARTIAL` claim;
7. the `verify_evidence` trace entry cannot produce evidence itself.

The test suite includes both happy-path and deliberate failure cases. Current result:

```text
7 passed
```

A valid partial answer has `verification.status=PASSED` and an explicit `PARTIAL` claim.
A response downgraded because a verification check failed has `verification.status=FAILED`.
That distinction is intentional and is available to the future evaluation harness.

## Important runtime note

The scaffold is written to run against the project's WSL PostgreSQL and document artifacts,
but this execution environment does not have your WSL database or a verified live LangGraph
installation. Therefore the fixture tests do not claim a live database or LLM run.

The LangGraph dependency remains isolated in `langgraph_agent.py`, so API/version changes stay
localized instead of spreading framework assumptions through the contract and verifier.

## Layout

```text
rc07_vertical_slice/
├── agent_contract.py
├── document_store.py
├── postgres_tool.py
├── verifier.py
├── rc07.py
├── langgraph_agent.py
├── main.py
├── fixtures/
│   └── rc07_document.json
├── tests/
│   ├── conftest.py
│   ├── test_contract.py
│   ├── test_rc07_fixture.py
│   ├── test_main_fixture_trace.py
│   ├── test_verifier_hardening.py
│   └── test_trace_integrity.py
├── requirements.txt
└── .env.example
```

## Local setup

Install the dependencies in your project virtualenv:

```bash
pip install -r requirements.txt
```

Set:

```bash
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/meridian
DOCUMENT_ROOT=../artifacts/documents
```

Run the regression suite from the project root:

```bash
pytest -q
```

Run the deterministic fixture:

```bash
python main.py --fixture
```

For the real RC-07 slice:

```bash
python main.py --shipment SH-4921 --database-url "$DATABASE_URL" --document-root "$DOCUMENT_ROOT"
```

The SQL tool is intentionally read-only and parameterized for v1. Text-to-SQL is deferred
until a later investigation actually requires it.
