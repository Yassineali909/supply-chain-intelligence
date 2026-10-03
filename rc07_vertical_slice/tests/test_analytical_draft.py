"""
Tests for the text-to-SQL drafting pipeline (step 3). Hermetic: the LLM is a scripted mock
and the schema is a fixed dict, so no Ollama and no Postgres are needed. These prove the
pipeline validates/refuses the model's output and that a malicious draft never slips through.
"""
import analytical_draft as ad
from analytical_draft import draft_and_validate, extract_sql


# A fixed schema standing in for load_schema()'s live result.
SCHEMA = {
    "shipments": ["shipment_code", "route_id", "carrier_id", "delay_days", "status"],
    "routes": ["route_id", "code", "port_id", "warehouse_id"],
    "carriers": ["carrier_id", "code"],
}


def scripted_llm(*responses):
    """Return an llm_call(system, user) that yields the given responses in order."""
    queue = list(responses)

    def _call(system, user):
        assert queue, "mock LLM ran out of scripted responses"
        return queue.pop(0)

    return _call


# --- extract_sql ------------------------------------------------------------------------

def test_extract_plain_sql():
    assert extract_sql("SELECT 1 FROM shipments") == "SELECT 1 FROM shipments"


def test_extract_strips_sql_fences():
    assert extract_sql("```sql\nSELECT 1 FROM shipments\n```") == "SELECT 1 FROM shipments"


def test_extract_strips_bare_fences_and_trailing_semicolon():
    assert extract_sql("```\nSELECT 1 FROM shipments;\n```") == "SELECT 1 FROM shipments"


def test_extract_drops_leading_prose():
    txt = "Sure! Here is the query you asked for:\nSELECT COUNT(*) FROM shipments"
    assert extract_sql(txt) == "SELECT COUNT(*) FROM shipments"


# --- happy paths ------------------------------------------------------------------------

def test_plain_draft_validates_and_gets_limit():
    llm = scripted_llm("SELECT COUNT(*) FROM shipments WHERE status = 'delayed'")
    res = draft_and_validate(llm, "how many delayed shipments?", SCHEMA)
    assert res.ok
    assert "LIMIT" in res.safe_sql
    assert res.referenced_tables == ("shipments",)
    assert res.attempts == 1


def test_fenced_draft_is_unwrapped_then_validated():
    llm = scripted_llm("```sql\nSELECT carrier_id, AVG(delay_days) FROM shipments GROUP BY carrier_id\n```")
    res = draft_and_validate(llm, "avg delay per carrier", SCHEMA)
    assert res.ok
    assert "AVG(delay_days)" in res.safe_sql


# --- the LLM is NOT trusted -------------------------------------------------------------

def test_malicious_draft_is_refused_not_executed():
    llm = scripted_llm("DROP TABLE shipments")
    # one attempt so the mock isn't asked for a retry it wasn't scripted for
    res = draft_and_validate(llm, "delete everything", SCHEMA, max_attempts=1)
    assert res.ok is False
    assert res.safe_sql is None
    assert "select" in res.reason.lower()


def test_schema_escape_draft_is_refused():
    llm = scripted_llm("SELECT * FROM pg_catalog.pg_tables")
    res = draft_and_validate(llm, "list system tables", SCHEMA, max_attempts=1)
    assert res.ok is False
    assert "pg_catalog" in res.reason.lower()


def test_cannot_answer_sentinel_refuses_cleanly():
    llm = scripted_llm("CANNOT_ANSWER")
    res = draft_and_validate(llm, "what is the CEO's salary?", SCHEMA, max_attempts=1)
    assert res.ok is False
    assert "cannot be answered" in res.reason.lower()
    assert res.safe_sql is None


# --- bounded retry ----------------------------------------------------------------------

def test_retry_recovers_from_a_bad_first_draft():
    # first draft references a non-allowlisted table; second is valid.
    llm = scripted_llm(
        "SELECT * FROM made_up_table",
        "SELECT COUNT(*) FROM shipments",
    )
    res = draft_and_validate(llm, "count shipments", SCHEMA, max_attempts=2)
    assert res.ok
    assert res.attempts == 2
    assert len(res.drafts) == 2          # both attempts captured for the trace
    assert "made_up_table" in res.drafts[0]


def test_retry_exhausted_refuses_with_reason():
    llm = scripted_llm(
        "SELECT * FROM made_up_table",
        "DELETE FROM shipments",
    )
    res = draft_and_validate(llm, "nonsense", SCHEMA, max_attempts=2)
    assert res.ok is False
    assert res.attempts == 2
    assert "failed validation" in res.reason.lower()
