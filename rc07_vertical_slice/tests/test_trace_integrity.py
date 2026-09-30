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


def test_verify_step_cannot_launder_unproduced_evidence():
    response = AgentResponse(
        run_id="RUN-CIRCULARITY",
        question="q",
        outcome=Outcome.SUPPORTED,
        answer="The shipment was delayed.",
        claims=[
            Claim(
                claim_id="CLM-ORPHAN",
                text="The shipment was delayed.",
                claim_type=ClaimType.ENTITY_FACT,
                support_status=SupportStatus.SUPPORTED,
                evidence_ids=["EVD-ORPHAN"],
            )
        ],
        evidence=[
            Evidence(
                evidence_id="EVD-ORPHAN",
                source_type=SourceType.SQL,
                source_ref="postgres:shipments",
                locator={"query_id": "Q-CIRCULAR"},
                fact="delay_days=8",
                relevance=Relevance.DIRECT,
            )
        ],
        tool_trace=[
            ToolTraceEntry(
                step=1,
                tool_call_id="TC-VERIFY",
                tool="verify_evidence",
                purpose="pretend verification produced the evidence",
                status="SUCCESS",
                input={},
                output_refs=["EVD-ORPHAN"],
            )
        ],
        verification=Verification(status="FAILED", checks=[]),
    )

    verified = verify_response(response)

    assert verified.verification.status == "FAILED"
    produced_check = next(c for c in verified.verification.checks if c.type == "EVIDENCE_PRODUCED_BY_TOOL")
    assert produced_check.status == "FAIL"
