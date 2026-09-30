from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_contract import AgentResponse


def fixture_response() -> AgentResponse:
    from verifier import verify_response
    from agent_contract import (
        Claim, ClaimType, Evidence, Outcome, Relevance, SourceType,
        SupportStatus, ToolTraceEntry, Verification, Timing,
    )

    response = AgentResponse(
        run_id="RUN-FIXTURE-RC07",
        question="What happened to shipment SH-4921?",
        outcome=Outcome.SUPPORTED,
        answer=(
            "Shipment SH-4921 arrived 8 days late. The incident report attributes the delay "
            "to a customs hold at PORT-ADR."
        ),
        claims=[
            Claim(
                claim_id="CLM-001",
                text="SH-4921 arrived 8 days late.",
                claim_type=ClaimType.NUMERIC,
                support_status=SupportStatus.SUPPORTED,
                evidence_ids=["EVD-001"],
            ),
            Claim(
                claim_id="CLM-002",
                text="The delay was caused by a customs hold at PORT-ADR.",
                claim_type=ClaimType.CAUSAL,
                support_status=SupportStatus.SUPPORTED,
                evidence_ids=["EVD-002"],
            ),
        ],
        evidence=[
            Evidence(
                evidence_id="EVD-001",
                source_type=SourceType.SQL,
                source_ref="postgres:shipments",
                locator={"query_id": "SQL-0001", "row_keys": ["SH-4921"]},
                fact="Shipment SH-4921 arrived 8 days late (delay_days=8).",
                relevance=Relevance.DIRECT,
            ),
            Evidence(
                evidence_id="EVD-002",
                source_type=SourceType.DOCUMENT,
                source_ref="DOC-FIXTURE-RC07",
                locator={"chunk_id": "DOC-FIXTURE-RC07:C01"},
                fact="INC-042 states that SH-4921 was held at PORT-ADR for customs clearance.",
                relevance=Relevance.DIRECT,
            ),
        ],
        tool_trace=[
            ToolTraceEntry(
                step=1, tool_call_id="TC-001", tool="query_database",
                purpose="retrieve shipment delay", status="SUCCESS",
                input={"query_id": "SQL-0001", "parameters": {"shipment_code": "SH-4921"}},
                output_refs=["EVD-001"],
            ),
            ToolTraceEntry(
                step=2, tool_call_id="TC-002", tool="search_documents",
                purpose="find shipment incident document", status="SUCCESS",
                input={"shipment_code": "SH-4921"}, output_refs=["EVD-002"],
            ),
        ],
        verification=Verification(status="FAILED", checks=[]),
        timing=Timing(),
    )
    response = verify_response(response)
    response.tool_trace.append(
        ToolTraceEntry(
            step=3, tool_call_id="TC-003", tool="verify_evidence",
            purpose="check claim/evidence bindings", status="SUCCESS",
            input={"claim_ids": [c.claim_id for c in response.claims]},
            output_refs=[],
        )
    )
    return response


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument("--shipment", default="SH-4921")
    parser.add_argument("--database-url")
    parser.add_argument("--document-root")
    args = parser.parse_args()

    if args.fixture:
        response = fixture_response()
    else:
        if not args.database_url or not args.document_root:
            parser.error("real mode requires --database-url and --document-root")
        from rc07 import investigate_rc07
        response = investigate_rc07(args.database_url, args.document_root, args.shipment)

    print(json.dumps(response.model_dump(mode="json"), indent=2, default=str))


if __name__ == "__main__":
    main()
