"""
RC-02 investigation: "Why is supplier <CODE> chronically late?"

Multi-step, deterministic assembly (Option A): calls three supplier query tools, builds
SQL evidence from each, and asserts ONE rigorous COMPARATIVE claim — the de-confounded
gap (supplier vs peers on clean routes). The causal interpretation stays in the answer
prose ("strongly indicates"), NOT asserted as a verified causal claim, because
observational data with one confounder controlled is not proof of causation.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from agent_contract import (
    AgentResponse, Claim, ClaimType, Evidence, Outcome, Relevance,
    SourceType, SupportStatus, Timing, ToolTraceEntry, Verification,
)
from postgres_tool import (
    supplier_overall, supplier_by_route_class, supplier_vs_peers_clean,
)
from verifier import verify_response


def _row(rows, key, val):
    return next((r for r in rows if r.get(key) == val), None)


def investigate_rc02(database_url: str, supplier_code: str = "S07",
                     question: str | None = None) -> AgentResponse:
    question = question or f"Why is supplier {supplier_code} chronically late?"
    started = time.perf_counter()
    tool_ms = 0
    traces, evidences, claims = [], [], []

    def run(tool, step, purpose, out_ev):
        nonlocal tool_ms
        t0 = time.perf_counter()
        res = tool(database_url, supplier_code)
        tool_ms += int((time.perf_counter() - t0) * 1000)
        traces.append(ToolTraceEntry(
            step=step, tool_call_id=res.trace["tool_call_id"], tool="query_database",
            purpose=purpose, status="SUCCESS" if res.rows else "ERROR",
            input={"parameters": res.trace["parameters"]}, output_refs=[out_ev],
        ))
        return res

    a = run(supplier_overall, 1, "overall delay for the supplier", "EVD-A")
    b = run(supplier_by_route_class, 2, "delay split by clean vs congested route", "EVD-B")
    c = run(supplier_vs_peers_clean, 3, "supplier vs peers on clean routes only", "EVD-C")

    if not (a.rows and b.rows and c.rows):
        return AgentResponse(
            run_id="RUN-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
            question=question, outcome=Outcome.INSUFFICIENT_EVIDENCE,
            answer=f"Could not retrieve enough data to assess supplier {supplier_code}.",
            claims=[], evidence=[], tool_trace=traces,
            verification=Verification(status="FAILED", checks=[]),
            timing=Timing(total_ms=int((time.perf_counter()-started)*1000), tool_ms=tool_ms),
        )

    overall = float(a.rows[0]["avg_delay_days"])
    clean = _row(b.rows, "route_class", "clean")
    clean_delay = float(clean["avg_delay_days"]) if clean else None
    this_c = _row(c.rows, "grp", "this_supplier")
    peers_c = _row(c.rows, "grp", "peers")
    this_delay = float(this_c["avg_delay_days"])
    peers_delay = float(peers_c["avg_delay_days"])
    gap = round(this_delay - peers_delay, 2)

    evidences.append(Evidence(
        evidence_id="EVD-A", source_type=SourceType.SQL, source_ref="postgres:shipments",
        locator={"query_id": "SQL-A", "supplier": supplier_code},
        fact=f"Supplier {supplier_code} overall averages {overall} days of delay across {a.rows[0]['shipment_count']} shipments.",
        relevance=Relevance.DIRECT,
    ))
    evidences.append(Evidence(
        evidence_id="EVD-B", source_type=SourceType.SQL, source_ref="postgres:shipments",
        locator={"query_id": "SQL-B", "supplier": supplier_code},
        fact=f"On clean routes {supplier_code} averages {clean_delay} days of delay; the supplier is late even without the congested port.",
        relevance=Relevance.DIRECT,
    ))
    evidences.append(Evidence(
        evidence_id="EVD-C", source_type=SourceType.SQL, source_ref="postgres:shipments",
        locator={"query_id": "SQL-C", "supplier": supplier_code},
        fact=(f"On clean routes (congested port excluded): {supplier_code} averages {this_delay} days "
              f"over {this_c['shipment_count']} shipments; peer suppliers average {peers_delay} days "
              f"over {peers_c['shipment_count']} shipments."),
        relevance=Relevance.DIRECT,
    ))

    claims.append(Claim(
        claim_id="CLM-CMP",
        text=(f"Supplier {supplier_code} averages {this_delay} days of delay on clean routes versus "
              f"{peers_delay} days for peer suppliers on the same routes, a gap of {gap} days that "
              f"persists with the congested-port factor removed."),
        claim_type=ClaimType.COMPARATIVE, support_status=SupportStatus.SUPPORTED,
        evidence_ids=["EVD-C"],
    ))

    answer = (
        f"Supplier {supplier_code} is chronically late: it averages {overall} days of delay overall. "
        f"Critically, the lateness persists on clean routes that avoid the congested port "
        f"({this_delay} days vs {peers_delay} days for peers on the same routes, a {gap}-day gap). "
        f"Because the gap remains once the congested-port factor is removed, this strongly indicates "
        f"the supplier itself, not its routing, is the source of the delays."
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
        purpose="check the comparative claim's figures against SQL evidence",
        status="SUCCESS" if verified.verification.status == "PASSED" else "ERROR",
        input={"claim_ids": [c.claim_id for c in verified.claims]}, output_refs=[],
    ))
    return verified
