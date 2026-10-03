"""
Tests for the analytical investigation (step 4) and the router precedence predicate
(step 5). Hermetic: the LLM is scripted, execution is injected, and the REAL verifier runs.
No Ollama, no Postgres.
"""
import pytest

from agent_contract import AgentResponse, ClaimType, Outcome, SupportStatus, SourceType, Relevance, Evidence, Claim, ToolTraceEntry, Verification
from verifier import verify_response
from analytical import investigate_analytical, is_analytical_question

SCHEMA = {
    "shipments": ["shipment_code", "route_id", "carrier_id", "delay_days", "status"],
    "invoices": ["invoice_id", "status", "amount"],
}


def scripted_llm(*responses):
    q = list(responses)

    def _call(system, user):
        assert q, "mock LLM out of responses"
        return q.pop(0)
    return _call


def fake_execute(columns, rows):
    def _exec(database_url, safe_sql, timeout_ms=5000):
        return columns, rows
    return _exec


def exploding_execute(database_url, safe_sql, timeout_ms=5000):
    raise AssertionError("execute must NOT be called when the draft is refused")


# --- happy path ------------------------------------------------------------------------

def test_scalar_count_is_supported_and_verified():
    llm = scripted_llm("SELECT COUNT(*) FROM shipments WHERE carrier_id = 3")
    resp = investigate_analytical(
        llm, "db://x", "how many shipments used CR3?",
        schema=SCHEMA, execute=fake_execute(["count"], [(142,)]))
    assert resp.outcome == Outcome.SUPPORTED
    assert resp.verification.status == "PASSED"
    agg = [c for c in resp.verification.checks if c.type == "AGGREGATE_CLAIM_MATCHES_SQL"]
    assert len(agg) == 1 and agg[0].status == "PASS"
    assert resp.claims[0].claim_type == ClaimType.AGGREGATE
    assert "142" in resp.claims[0].text
    # transparency: the generated SQL is surfaced in the answer and evidence locator
    assert "SELECT COUNT(*)" in resp.answer
    assert "generated_sql" in resp.evidence[0].locator


def test_decimal_average_is_supported():
    llm = scripted_llm("SELECT AVG(delay_days) FROM shipments")
    resp = investigate_analytical(
        llm, "db://x", "what is the average delay in March?",
        schema=SCHEMA, execute=fake_execute(["avg"], [(4.27,)]))
    assert resp.outcome == Outcome.SUPPORTED
    assert "4.27" in resp.claims[0].text


# --- the LLM is not trusted; failures refuse honestly ----------------------------------

def test_malicious_draft_refuses_without_executing():
    llm = scripted_llm("DROP TABLE shipments")
    resp = investigate_analytical(
        llm, "db://x", "delete it all", schema=SCHEMA,
        execute=exploding_execute, max_attempts=1)
    assert resp.outcome == Outcome.INSUFFICIENT_EVIDENCE
    assert resp.claims == []
    assert "could not produce a safe query" in resp.answer.lower()


def test_schema_error_refuses():
    from sql_executor import SchemaError

    def bad_exec(database_url, safe_sql, timeout_ms=5000):
        raise SchemaError('column "nope" does not exist')

    llm = scripted_llm("SELECT COUNT(*) FROM shipments")
    resp = investigate_analytical(llm, "db://x", "count things",
                                  schema=SCHEMA, execute=bad_exec)
    assert resp.outcome == Outcome.INSUFFICIENT_EVIDENCE
    assert "does not exist" in resp.answer


def test_three_column_result_is_refused():
    # A 2-col GROUP BY is now a supported grouped result; 3+ columns still can't be
    # verified (which column is "the answer"?) -> honest refusal.
    llm = scripted_llm("SELECT carrier_id, status, COUNT(*) FROM shipments GROUP BY carrier_id, status")
    resp = investigate_analytical(
        llm, "db://x", "counts per carrier and status", schema=SCHEMA,
        execute=fake_execute(["carrier_id", "status", "n"], [(1, "ok", 2), (2, "late", 3)]))
    assert resp.outcome == Outcome.INSUFFICIENT_EVIDENCE
    assert "shape" in resp.answer or "can't verify" in resp.answer


def test_empty_value_refuses():
    llm = scripted_llm("SELECT AVG(delay_days) FROM shipments WHERE 1=0")
    resp = investigate_analytical(
        llm, "db://x", "avg of nothing", schema=SCHEMA,
        execute=fake_execute(["avg"], [(None,)]))
    assert resp.outcome == Outcome.INSUFFICIENT_EVIDENCE
    assert "no value" in resp.answer.lower()


# --- mutation: the AGGREGATE check must catch a wrong value (prove the red) -------------

def test_aggregate_check_catches_transcription_mismatch():
    # Build a response by hand where the claim value disagrees with the SQL evidence.
    resp = AgentResponse(
        run_id="RUN", question="q", outcome=Outcome.SUPPORTED,
        answer="The query answering this question returned a value of 999.",
        claims=[Claim(claim_id="CLM-AGG",
                      text="The query answering this question returned a value of 999.",
                      claim_type=ClaimType.AGGREGATE, support_status=SupportStatus.SUPPORTED,
                      evidence_ids=["EVD-AGG"])],
        evidence=[Evidence(evidence_id="EVD-AGG", source_type=SourceType.SQL,
                           source_ref="postgres:analytical", locator={},
                           fact="The validated query returned 142.", relevance=Relevance.DIRECT)],
        tool_trace=[ToolTraceEntry(step=1, tool_call_id="TC-SQL", tool="query_database",
                                   purpose="p", status="SUCCESS", input={}, output_refs=["EVD-AGG"])],
        verification=Verification(status="FAILED", checks=[]))
    out = verify_response(resp)
    agg = [c for c in out.verification.checks if c.type == "AGGREGATE_CLAIM_MATCHES_SQL"][0]
    assert agg.status == "FAIL"
    assert out.outcome == Outcome.PARTIALLY_SUPPORTED   # SUPPORTED got downgraded


# --- router precedence predicate (step 5) ----------------------------------------------

@pytest.mark.parametrize("q", [
    "how many shipments used CR3?",          # count + table noun, entity present -> analytical
    "count of disputed invoices",            # count + table noun
    "what is the average delay in March?",   # aggregate, no entity
    "how many suppliers do we have?",        # count + table noun
])
def test_questions_that_ARE_analytical(q):
    assert is_analytical_question(q) is True


@pytest.mark.parametrize("q", [
    "why is supplier S07 chronically late?",          # RC-02
    "average delay for S07",                          # aggregate BUT entity -> supplier owns it
    "how many days late is S07 on average?",          # delay-of-entity, not a row count -> supplier
    "is carrier CR3 getting worse?",                  # RC-03 trend
    "what happened to shipment SH-4921?",             # RC-07
    "why are WH-2 deliveries slow?",                  # RC-04
    "which supplier is the worst?",                   # ranking
    "which customers are affected by port congestion?",  # RC-05 impact
    "why are shipments through PORT-GEN delayed in Q1?",  # RC-01
])
def test_questions_that_are_NOT_analytical(q):
    assert is_analytical_question(q) is False


# ============================== MULTI-ROW (GROUPED) ==============================

SCHEMA_G = {
    "shipments": ["shipment_code", "route_id", "carrier_id", "delay_days", "status"],
    "carriers": ["carrier_id", "code"],
}
GROUPED_SQL = ("SELECT c.code, AVG(s.delay_days) FROM shipments s "
               "JOIN carriers c ON s.carrier_id = c.carrier_id GROUP BY c.code")
MONTH_SQL = ("SELECT EXTRACT(MONTH FROM planned_departure), AVG(delay_days) "
             "FROM shipments GROUP BY 1")
TWO_METRIC_SQL = "SELECT COUNT(*), AVG(delay_days) FROM shipments"


def test_grouped_result_builds_one_claim_per_row():
    llm = scripted_llm(GROUPED_SQL)
    resp = investigate_analytical(
        llm, "db://x", "average delay per carrier", schema=SCHEMA_G,
        execute=fake_execute(["code", "avg"], [("CR1", 1.2), ("CR3", 2.81), ("CR5", 0.95)]))
    assert resp.outcome == Outcome.SUPPORTED
    assert resp.verification.status == "PASSED"
    aggs = [c for c in resp.verification.checks if c.type == "AGGREGATE_CLAIM_MATCHES_SQL"]
    assert len(aggs) == 3 and all(c.status == "PASS" for c in aggs)
    assert len(resp.claims) == 3 and len(resp.evidence) == 3
    # labels live in the locator, not the scanned claim text
    assert {e.locator["group"] for e in resp.evidence} == {"CR1", "CR3", "CR5"}
    assert "CR3" in resp.answer and "2.81" in resp.answer


def test_grouped_numeric_label_month_works():
    # The reason we chose design (b): a numeric group label (month) must not break
    # value extraction, because the label is isolated in the locator.
    llm = scripted_llm(MONTH_SQL)
    resp = investigate_analytical(
        llm, "db://x", "average delay per month", schema=SCHEMA_G,
        execute=fake_execute(["month", "avg"], [(1, 2.1), (2, 3.4), (3, 1.9)]))
    assert resp.outcome == Outcome.SUPPORTED
    aggs = [c for c in resp.verification.checks if c.type == "AGGREGATE_CLAIM_MATCHES_SQL"]
    assert len(aggs) == 3 and all(c.status == "PASS" for c in aggs)
    # each claim carries exactly its value, never the month number
    vals = sorted(float(c.detail.split("value=")[1].split(";")[0]) for c in aggs)
    assert vals == [1.9, 2.1, 3.4]


def test_two_metrics_without_group_by_is_refused():
    llm = scripted_llm(TWO_METRIC_SQL)
    resp = investigate_analytical(
        llm, "db://x", "count and average delay", schema=SCHEMA_G,
        execute=fake_execute(["count", "avg"], [(4717, 1.72)]))
    assert resp.outcome == Outcome.INSUFFICIENT_EVIDENCE
    assert "can't verify" in resp.answer or "shape" in resp.answer


def test_grouped_nonnumeric_value_column_is_refused():
    llm = scripted_llm(GROUPED_SQL)
    resp = investigate_analytical(
        llm, "db://x", "something per carrier", schema=SCHEMA_G,
        execute=fake_execute(["avg", "code"], [(1.2, "CR1"), (3.4, "CR3")]))
    assert resp.outcome == Outcome.INSUFFICIENT_EVIDENCE
    assert "not numeric" in resp.answer


def test_grouped_too_many_rows_is_refused():
    llm = scripted_llm(GROUPED_SQL)
    big = [(f"G{i}", float(i)) for i in range(26)]  # 26 > MAX_GROUPS
    resp = investigate_analytical(
        llm, "db://x", "avg delay per group", schema=SCHEMA_G,
        execute=fake_execute(["g", "avg"], big))
    assert resp.outcome == Outcome.INSUFFICIENT_EVIDENCE
    assert "groups" in resp.answer


def test_grouped_null_value_is_refused():
    llm = scripted_llm(GROUPED_SQL)
    resp = investigate_analytical(
        llm, "db://x", "avg delay per carrier", schema=SCHEMA_G,
        execute=fake_execute(["code", "avg"], [("CR1", 1.2), ("CR3", None)]))
    assert resp.outcome == Outcome.INSUFFICIENT_EVIDENCE


def test_per_row_mutation_is_caught_by_verifier():
    # The investigation shares one formatted value between a row's claim and evidence, so
    # they cannot diverge by construction (that IS the transcription guarantee). The
    # meaningful "prove the red" is at the verifier: a hand-built multi-row response with
    # ONE corrupted row must fail that row's check and downgrade the whole response.
    rows = [("CR1", 1.2), ("CR3", 2.81), ("CR5", 0.95)]
    evid, claims, refs = [], [], []
    for i, (label, value) in enumerate(rows):
        eid, cid = f"EVD-{i}", f"CLM-{i}"
        refs.append(eid)
        evid.append(Evidence(evidence_id=eid, source_type=SourceType.SQL,
                             source_ref="postgres:analytical", locator={"group": label},
                             fact=f"The validated query returned {value} for this group.",
                             relevance=Relevance.DIRECT))
        claim_value = 999.0 if i == 1 else value          # corrupt the 2nd row's claim
        claims.append(Claim(claim_id=cid, text=f"For one group, the value is {claim_value}.",
                            claim_type=ClaimType.AGGREGATE, support_status=SupportStatus.SUPPORTED,
                            evidence_ids=[eid]))
    resp = AgentResponse(run_id="R", question="per carrier", outcome=Outcome.SUPPORTED,
                         answer="table", claims=claims, evidence=evid,
                         tool_trace=[ToolTraceEntry(step=1, tool_call_id="T1", tool="query_database",
                                                    purpose="grouped", status="SUCCESS", input={},
                                                    output_refs=refs)],
                         verification=Verification(status="FAILED", checks=[]))
    out = verify_response(resp)
    aggs = [c for c in out.verification.checks if c.type == "AGGREGATE_CLAIM_MATCHES_SQL"]
    assert sum(c.status == "FAIL" for c in aggs) == 1
    assert sum(c.status == "PASS" for c in aggs) == 2
    assert out.outcome == Outcome.PARTIALLY_SUPPORTED
