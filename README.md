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

## Important runtime note

The scaffold is written to run against the project's WSL PostgreSQL and document artifacts,
but this execution environment does not have your WSL database or LangGraph installation.
Therefore the code is structured for local project integration; the fixture tests do not
claim a live database run.

The current web verification attempt also did not return official LangGraph documentation,
so the LangGraph adapter is intentionally isolated in `langgraph_agent.py`. This keeps any
future API-version adjustment localized instead of spreading framework assumptions through
the contract and verification code.

## Layout

```text
rc07_vertical_slice/
├── agent_contract.py       # Pydantic v1 response/evidence models
├── document_store.py       # stable JSON document lookup/search adapter
├── postgres_tool.py        # SQL read-only tool with reproducible trace records
├── verifier.py             # deterministic contract/evidence verification
├── rc07.py                 # RC-07 investigation orchestration
├── langgraph_agent.py      # optional LangGraph wrapper
├── main.py                 # CLI entry point
├── fixtures/
│   └── rc07_document.json
├── tests/
│   ├── test_contract.py
│   └── test_rc07_fixture.py
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

Then the deterministic fixture mode can be exercised without a database:

```bash
python main.py --fixture
```

For the real slice:

```bash
python main.py --shipment SH-4921 --database-url "$DATABASE_URL" --document-root "$DOCUMENT_ROOT"
```

## Contract invariant

No final claim may exist without an evidence binding, and no evidence binding may point
to a non-existent evidence item. The verifier enforces this before allowing `SUPPORTED`.

The SQL tool is intentionally read-only for v1. It exposes a narrow parameterized query for
RC-07 rather than attempting Text-to-SQL prematurely.
