from agent_contract import Claim, ClaimType, Evidence, Outcome, Relevance, SourceType, SupportStatus, ToolTraceEntry, Verification
from verifier import verify_response
from agent_contract import AgentResponse


def test_claim_evidence_binding_passes():
    response = AgentResponse(
        run_id="RUN-TEST",
        question="q",
        outcome=Outcome.SUPPORTED,
        answer="Shipment was delayed.",
        claims=[Claim(claim_id="CLM-1", text="Shipment was delayed.", claim_type=ClaimType.ENTITY_FACT, support_status=SupportStatus.SUPPORTED, evidence_ids=["EVD-1"])],
        evidence=[Evidence(evidence_id="EVD-1", source_type=SourceType.SQL, source_ref="postgres:shipments", locator={"query_id":"Q1"}, fact="delay_days=8", relevance=Relevance.DIRECT)],
        tool_trace=[ToolTraceEntry(step=1, tool_call_id="TC-1", tool="query_database", purpose="test", status="SUCCESS", input={}, output_refs=["EVD-1"])],
        verification=Verification(status="FAILED", checks=[]),
    )
    response = verify_response(response)
    assert response.verification.status == "PASSED"
