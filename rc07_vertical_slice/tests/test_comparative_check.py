"""
Verifier COMPARATIVE check tests (deterministic, no DB).

Pins RC-02's check: a COMPARATIVE claim's two base figures must be grounded in SQL
evidence, and any derived gap figure must be arithmetically correct. Mutation-tested:
weakening the gap-arithmetic check makes test_wrong_derived_gap_fails go red. The
base-grounding and gap checks are intentionally coupled (defense in depth).
"""
from agent_contract import (
    AgentResponse, Claim, ClaimType, Evidence, Outcome, Relevance,
    SourceType, SupportStatus, ToolTraceEntry, Verification,
)
from verifier import verify_response


def _resp(claim_text, evidence_fact):
    return AgentResponse(
        run_id="RUN-CMP-TEST", question="test", outcome=Outcome.SUPPORTED,
        answer=claim_text,
        claims=[Claim(claim_id="CLM-CMP", text=claim_text, claim_type=ClaimType.COMPARATIVE,
                      support_status=SupportStatus.SUPPORTED, evidence_ids=["EVD-C"])],
        evidence=[Evidence(evidence_id="EVD-C", source_type=SourceType.SQL,
                           source_ref="postgres:shipments", locator={"query_id": "SQL-C"},
                           fact=evidence_fact, relevance=Relevance.DIRECT)],
        tool_trace=[ToolTraceEntry(step=1, tool_call_id="TC-C", tool="query_database",
                                   purpose="vs peers", status="SUCCESS", input={},
                                   output_refs=["EVD-C"])],
        verification=Verification(status="FAILED", checks=[]),
    )


EV = "On clean routes: S07 averages 5.27 days over 183 shipments; peers average 1.0 days over 1794 shipments."


def _cmp_check(resp):
    v = verify_response(resp)
    return next(c for c in v.verification.checks if c.type == "COMPARATIVE_CLAIM_MATCHES_SQL"), v


def test_correct_comparison_with_derived_gap_passes():
    claim = "S07 averages 5.27 days versus 1.0 days for peers, a gap of 4.27 days."
    chk, v = _cmp_check(_resp(claim, EV))
    assert chk.status == "PASS"
    assert v.verification.status == "PASSED"


def test_wrong_base_figure_fails():
    claim = "S07 averages 3.0 days versus 1.0 days for peers, a gap of 2.0 days."
    chk, v = _cmp_check(_resp(claim, EV))
    assert chk.status == "FAIL"
    assert v.verification.status == "FAILED"


def test_wrong_derived_gap_fails():
    claim = "S07 averages 5.27 days versus 1.0 days for peers, a gap of 9.99 days."
    chk, v = _cmp_check(_resp(claim, EV))
    assert chk.status == "FAIL"


def test_no_gap_fails():
    ev = "On clean routes: S07 averages 1.0 days; peers average 1.0 days."
    claim = "S07 averages 1.0 days versus 1.0 days for peers."
    chk, v = _cmp_check(_resp(claim, ev))
    assert chk.status == "FAIL"


def test_one_fabricated_base_figure_fails_even_with_consistent_gap():
    ev = "On clean routes: S07 averages 5.27 days; peers average 1.0 days."
    claim = "S07 averages 5.27 days versus 2.0 days for peers, a gap of 3.27 days."
    chk, v = _cmp_check(_resp(claim, ev))
    assert chk.status == "FAIL"
