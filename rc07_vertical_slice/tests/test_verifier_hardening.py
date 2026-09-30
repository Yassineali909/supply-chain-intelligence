from agent_contract import (
    AgentResponse,
    Claim,
    ClaimType,
    Evidence,
    Outcome,
    Relevance,
    SourceType,
    SupportStatus,
    ToolTraceEntry,
    Verification,
)
from verifier import verify_response


def _base_response(*, outcome, answer, claims, evidence):
    return AgentResponse(
        run_id="RUN-TEST-HARDENING",
        question="test",
        outcome=outcome,
        answer=answer,
        claims=claims,
        evidence=evidence,
        tool_trace=[
            ToolTraceEntry(
                step=1,
                tool_call_id="TC-SQL",
                tool="query_database",
                purpose="test SQL evidence",
                status="SUCCESS",
                input={},
                output_refs=[e.evidence_id for e in evidence if e.source_type == SourceType.SQL],
            ),
            ToolTraceEntry(
                step=2,
                tool_call_id="TC-DOC",
                tool="search_documents",
                purpose="test document evidence",
                status="SUCCESS",
                input={},
                output_refs=[e.evidence_id for e in evidence if e.source_type == SourceType.DOCUMENT],
            ),
        ],
        verification=Verification(status="FAILED", checks=[]),
    )


def test_numeric_claim_mismatch_fails_and_downgrades():
    response = _base_response(
        outcome=Outcome.SUPPORTED,
        answer="Shipment SH-4921 arrived 3 days late.",
        claims=[
            Claim(
                claim_id="CLM-NUM",
                text="SH-4921 arrived 3 days late.",
                claim_type=ClaimType.NUMERIC,
                support_status=SupportStatus.SUPPORTED,
                evidence_ids=["EVD-SQL"],
            )
        ],
        evidence=[
            Evidence(
                evidence_id="EVD-SQL",
                source_type=SourceType.SQL,
                source_ref="postgres:shipments",
                locator={"query_id": "SQL-1", "row_keys": ["SH-4921"]},
                fact="Shipment SH-4921 arrived 8 days late (delay_days=8).",
                relevance=Relevance.DIRECT,
            )
        ],
    )

    verified = verify_response(response)

    assert verified.verification.status == "FAILED"
    assert verified.outcome == Outcome.PARTIALLY_SUPPORTED
    check = next(c for c in verified.verification.checks if c.type == "NUMERIC_CLAIM_MATCHES_SQL")
    assert check.status == "FAIL"


def test_contextual_document_cannot_support_supported_causal_claim():
    response = _base_response(
        outcome=Outcome.SUPPORTED,
        answer="The delay was caused by port congestion.",
        claims=[
            Claim(
                claim_id="CLM-CAUSE",
                text="The delay was caused by port congestion.",
                claim_type=ClaimType.CAUSAL,
                support_status=SupportStatus.SUPPORTED,
                evidence_ids=["EVD-DOC"],
            )
        ],
        evidence=[
            Evidence(
                evidence_id="EVD-DOC",
                source_type=SourceType.DOCUMENT,
                source_ref="DOC-CONTEXT",
                locator={"chunk_id": "DOC-CONTEXT:C01"},
                fact="PORT-GEN experienced congestion during the quarter; this document does not identify the cause of SH-5317.",
                relevance=Relevance.CONTEXTUAL,
            )
        ],
    )

    verified = verify_response(response)

    assert verified.verification.status == "FAILED"
    assert verified.outcome == Outcome.INSUFFICIENT_EVIDENCE
    check = next(c for c in verified.verification.checks if c.type == "CAUSAL_REQUIRES_DIRECT_DOCUMENTARY_EVIDENCE")
    assert check.status == "FAIL"


def test_legitimate_partial_is_distinct_from_verification_downgrade():
    response = _base_response(
        outcome=Outcome.PARTIALLY_SUPPORTED,
        answer="CR3's delay has increased over time, but the available evidence does not establish a single cause.",
        claims=[
            Claim(
                claim_id="CLM-TREND",
                text="CR3's delay increased over time.",
                claim_type=ClaimType.TREND,
                support_status=SupportStatus.PARTIAL,
                evidence_ids=["EVD-TREND"],
            )
        ],
        evidence=[
            Evidence(
                evidence_id="EVD-TREND",
                source_type=SourceType.SQL,
                source_ref="postgres:shipments",
                locator={"query_id": "SQL-TREND"},
                fact="CR3 average delay increased from 2.10 days to 4.61 days.",
                relevance=Relevance.DIRECT,
            )
        ],
    )

    verified = verify_response(response)

    assert verified.verification.status == "PASSED"
    assert verified.outcome == Outcome.PARTIALLY_SUPPORTED
    partial_check = next(c for c in verified.verification.checks if c.type == "LEGITIMATE_PARTIAL_OUTCOME")
    assert partial_check.status == "PASS"


def test_partial_outcome_without_partial_claim_fails():
    """
    Negative case for LEGITIMATE_PARTIAL_OUTCOME: a PARTIALLY_SUPPORTED response that
    contains NO claim with support_status=PARTIAL must FAIL verification. Without this,
    the PARTIAL semantics check has no teeth (a mutation that always passes it would go
    undetected). This is the failure-path counterpart to the positive PARTIAL test.
    """
    response = _base_response(
        outcome=Outcome.PARTIALLY_SUPPORTED,
        answer="CR3's delay increased over time.",
        claims=[
            Claim(
                claim_id="CLM-TREND",
                text="CR3's delay increased over time.",
                claim_type=ClaimType.TREND,
                support_status=SupportStatus.SUPPORTED,  # NOT partial — this is the defect
                evidence_ids=["EVD-TREND"],
            )
        ],
        evidence=[
            Evidence(
                evidence_id="EVD-TREND",
                source_type=SourceType.SQL,
                source_ref="postgres:shipments",
                locator={"query_id": "SQL-TREND"},
                fact="CR3 average delay increased from 2.10 days to 4.61 days.",
                relevance=Relevance.DIRECT,
            )
        ],
    )

    verified = verify_response(response)

    partial_check = next(
        c for c in verified.verification.checks if c.type == "LEGITIMATE_PARTIAL_OUTCOME"
    )
    assert partial_check.status == "FAIL"
    assert verified.verification.status == "FAILED"
