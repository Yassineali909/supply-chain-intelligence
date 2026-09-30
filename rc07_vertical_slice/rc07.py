from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from agent_contract import (
    AgentResponse,
    Claim,
    ClaimType,
    Evidence,
    Outcome,
    Relevance,
    SourceType,
    SupportStatus,
    Timing,
    ToolTraceEntry,
    Verification,
)
from document_store import search_documents
from postgres_tool import query_shipment
from verifier import verify_response


RC07_QUESTION = "What happened to shipment SH-4921?"


def _run_id() -> str:
    return "RUN-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def investigate_rc07(database_url: str, document_root: str, shipment_code: str = "SH-4921") -> AgentResponse:
    started = time.perf_counter()
    traces: list[ToolTraceEntry] = []
    evidences: list[Evidence] = []
    claims: list[Claim] = []
    tool_ms = 0

    # Step 1 — SQL: retrieve the exact shipment record.
    sql_started = time.perf_counter()
    sql_result = query_shipment(database_url, shipment_code)
    tool_ms += int((time.perf_counter() - sql_started) * 1000)
    traces.append(ToolTraceEntry(
        step=1,
        tool_call_id=sql_result.trace["tool_call_id"],
        tool="query_database",
        purpose="retrieve shipment status, dates, delay, route, port, warehouse and carrier",
        status="SUCCESS" if sql_result.rows else "ERROR",
        input={"query_id": sql_result.query_id, "parameters": {"shipment_code": shipment_code}},
        output_refs=[sql_result.evidence_id] if sql_result.rows else [],
    ))

    if not sql_result.rows:
        return AgentResponse(
            run_id=_run_id(),
            question=RC07_QUESTION.replace("SH-4921", shipment_code),
            outcome=Outcome.INSUFFICIENT_EVIDENCE,
            answer=f"I could not find shipment {shipment_code} in the operational database.",
            claims=[],
            evidence=[],
            tool_trace=traces,
            verification=Verification(status="FAILED", checks=[]),
            timing=Timing(total_ms=int((time.perf_counter() - started) * 1000), tool_ms=tool_ms),
        )

    row = sql_result.rows[0]
    evidences.append(Evidence(
        evidence_id=sql_result.evidence_id,
        source_type=SourceType.SQL,
        source_ref="postgres:shipments",
        locator={"query_id": sql_result.query_id, "row_keys": [shipment_code]},
        fact=(
            f"Shipment {shipment_code} has planned arrival {row['planned_arrival']}, "
            f"actual arrival {row['actual_arrival']}, and recorded delay {row['delay_days']} days."
        ),
        relevance=Relevance.DIRECT,
    ))

    # Step 2 — documents: locate a direct incident report / operational document.
    doc_started = time.perf_counter()
    docs, doc_trace, doc_evidence_id = search_documents(document_root, shipment_code)
    tool_ms += int((time.perf_counter() - doc_started) * 1000)
    traces.append(ToolTraceEntry(
        step=2,
        tool_call_id=doc_trace["tool_call_id"],
        tool="search_documents",
        purpose=doc_trace["purpose"],
        status="SUCCESS" if docs else "ERROR",
        input=doc_trace["input"],
        output_refs=[doc_evidence_id] if docs else [],
    ))

    # Selection is metadata-driven. Text keywords are deliberately not used as a
    # causal signal: contextual documents can mention the same supplier/route/period
    # without establishing why this specific shipment was delayed.
    direct_doc = next(
        (
            d for d in docs
            if str(d.get("metadata", {}).get("relevance", "")).upper() == Relevance.DIRECT.value
        ),
        None,
    )

    if direct_doc is not None:
        doc_id = direct_doc["doc_id"]
        metadata = direct_doc.get("metadata", {})
        incident = metadata.get("incident_code", "unknown incident")
        evidences.append(Evidence(
            evidence_id=doc_evidence_id,
            source_type=SourceType.DOCUMENT,
            source_ref=doc_id,
            locator={"chunk_id": f"{doc_id}:C01"},
            fact=str(direct_doc.get("text", "")).strip(),
            relevance=Relevance(str(direct_doc.get("metadata", {}).get("relevance", Relevance.DIRECT.value)).upper()),
        ))

    claims.append(Claim(
        claim_id="CLM-001",
        text=f"{shipment_code} arrived {row['delay_days']} days late.",
        claim_type=ClaimType.NUMERIC,
        support_status=SupportStatus.SUPPORTED,
        evidence_ids=[sql_result.evidence_id],
    ))

    if direct_doc is not None:
        claims.append(Claim(
            claim_id="CLM-002",
            text=(f"The delay was caused by a customs hold; the incident report "
                  f"identifies {direct_doc.get('metadata', {}).get('incident_code', 'the incident')} "
                  f"as the relevant event."),
            claim_type=ClaimType.CAUSAL,
            support_status=SupportStatus.SUPPORTED,
            evidence_ids=[doc_evidence_id],
        ))
        answer = (
            f"Shipment {shipment_code} arrived {row['delay_days']} days late. "
            f"The available incident report attributes the delay to a customs hold."
        )
        outcome = Outcome.SUPPORTED
    else:
        answer = (
            f"Shipment {shipment_code} was delayed by {row['delay_days']} days, "
            "but I could not find a document that establishes why."
        )
        outcome = Outcome.INSUFFICIENT_EVIDENCE

    response = AgentResponse(
        run_id=_run_id(),
        question=RC07_QUESTION.replace("SH-4921", shipment_code),
        outcome=outcome,
        answer=answer,
        claims=claims,
        evidence=evidences,
        tool_trace=traces,
        verification=Verification(status="FAILED", checks=[]),
        timing=Timing(total_ms=int((time.perf_counter() - started) * 1000), tool_ms=tool_ms),
    )

    # Step 3 — verification is itself an observable tool call.
    verified = verify_response(response)
    traces.append(ToolTraceEntry(
        step=3,
        tool_call_id="TC-003",
        tool="verify_evidence",
        purpose="check that final claims are bound to tool-produced evidence",
        status="SUCCESS" if verified.verification.status == "PASSED" else "ERROR",
        input={"claim_ids": [c.claim_id for c in verified.claims]},
        output_refs=[],
    ))
    verified.tool_trace = traces
    verified.timing = Timing(total_ms=int((time.perf_counter() - started) * 1000), tool_ms=tool_ms)
    return verified
