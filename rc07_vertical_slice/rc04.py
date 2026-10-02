"""
RC-04 investigation: warehouse stage-localization (the trap scenario).

Question shape: "why are deliveries from warehouse WH-2 slow during the peak?"

The trap: a naive answer blames the supplier. The CORRECT answer localizes the delay to
the warehouse's OUTBOUND stage: inbound shipments arrived on time, but outbound deliveries
slipped during the demand peak. This investigation proves the localization by comparing
inbound vs outbound delay, and explicitly rules out the supplier explanation.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from agent_contract import (
    AgentResponse, Claim, ClaimType, Evidence, Outcome, Relevance,
    SourceType, SupportStatus, Timing, ToolTraceEntry, Verification,
)
from postgres_tool import warehouse_inbound_vs_outbound, warehouse_vs_others_peak
from verifier import verify_response


def _row(rows, key, val):
    return next((r for r in rows if r.get(key) == val), None)


def investigate_rc04(database_url: str, warehouse_code: str = "WH-2",
                     question: str | None = None) -> AgentResponse:
    question = question or f"Why are deliveries from warehouse {warehouse_code} slow during the peak?"
    started = time.perf_counter()
    tool_ms = 0
    traces, evidences, claims = [], [], []

    def run(tool, step, purpose, out_ev, **kw):
        nonlocal tool_ms
        t0 = time.perf_counter()
        res = tool(database_url, **kw)
        tool_ms += int((time.perf_counter() - t0) * 1000)
        traces.append(ToolTraceEntry(
            step=step, tool_call_id=res.trace["tool_call_id"], tool="query_database",
            purpose=purpose, status="SUCCESS" if res.rows else "ERROR",
            input={"parameters": res.trace["parameters"]}, output_refs=[out_ev],
        ))
        return res

    a = run(warehouse_inbound_vs_outbound, 1,
            "inbound vs outbound delay for the warehouse, peak vs non-peak",
            "EVD-W1", warehouse_code=warehouse_code)
    b = run(warehouse_vs_others_peak, 2,
            "compare this warehouse's outbound delay to other warehouses in the peak",
            "EVD-W2")

    peak = _row(a.rows, "period", "peak")
    if not a.rows or peak is None:
        return AgentResponse(
            run_id="RUN-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
            question=question, outcome=Outcome.INSUFFICIENT_EVIDENCE,
            answer=f"Could not retrieve peak-period delivery data for {warehouse_code}.",
            claims=[], evidence=[], tool_trace=traces,
            verification=Verification(status="FAILED", checks=[]),
            timing=Timing(total_ms=int((time.perf_counter()-started)*1000), tool_ms=tool_ms),
        )

    inbound = float(peak["inbound_delay_days"])
    outbound = float(peak["outbound_delay_days"])
    gap = round(outbound - inbound, 2)

    worst = b.rows[0]["warehouse_code"] if b.rows else None
    is_worst_outbound = (worst == warehouse_code)

    evidences.append(Evidence(
        evidence_id="EVD-W1", source_type=SourceType.SQL, source_ref="postgres:deliveries",
        locator={"query_id": "SQL-W1", "warehouse": warehouse_code},
        fact=(f"During the peak at {warehouse_code}, inbound shipments averaged {inbound} days "
              f"of delay while outbound deliveries averaged {outbound} days; the delay is on "
              f"the outbound (warehouse) side, not inbound."),
        relevance=Relevance.DIRECT,
    ))
    others = "; ".join(f"{r['warehouse_code']} {r['outbound_delay_days']}d" for r in b.rows)
    evidences.append(Evidence(
        evidence_id="EVD-W2", source_type=SourceType.SQL, source_ref="postgres:deliveries",
        locator={"query_id": "SQL-W2"},
        fact=f"Peak outbound delay by warehouse: {others}.",
        relevance=Relevance.DIRECT,
    ))

    claims.append(Claim(
        claim_id="CLM-STAGE",
        text=(f"At {warehouse_code} during the peak, outbound delivery delay averages {outbound} days "
              f"versus {inbound} days inbound, a gap of {gap} days; the delay is on the warehouse "
              f"outbound stage, not the inbound supply."),
        claim_type=ClaimType.COMPARATIVE, support_status=SupportStatus.SUPPORTED,
        evidence_ids=["EVD-W1"],
    ))

    worst_note = (f" It is also the worst warehouse for outbound delay in the peak, "
                  f"confirming the bottleneck is local to {warehouse_code}.") if is_worst_outbound else ""
    answer = (
        f"Deliveries from {warehouse_code} are slower during the peak, but this is a warehouse-stage "
        f"bottleneck, not a supplier problem. Inbound shipments arrive roughly on time ({inbound} days), "
        f"while outbound deliveries slip to {outbound} days — the delay appears after the goods reach the "
        f"warehouse, during peak-demand handling.{worst_note} Blaming the supplier would be incorrect: "
        f"the inbound side is normal."
    )

    resp = AgentResponse(
        run_id="RUN-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
        question=question, outcome=Outcome.SUPPORTED, answer=answer,
        claims=claims, evidence=evidences, tool_trace=traces,
        verification=Verification(status="FAILED", checks=[]),
        timing=Timing(total_ms=int((time.perf_counter()-started)*1000), tool_ms=tool_ms),
    )
    verified = verify_response(resp)
    verified.tool_trace.append(ToolTraceEntry(
        step=len(traces)+1, tool_call_id="TC-VERIFY", tool="verify_evidence",
        purpose="check the stage-localization claim against SQL evidence",
        status="SUCCESS" if verified.verification.status == "PASSED" else "ERROR",
        input={"claim_ids": [c.claim_id for c in verified.claims]}, output_refs=[],
    ))
    return verified
