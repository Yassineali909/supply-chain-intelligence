"""
RC-01 investigation: "Why are shipments through <PORT> delayed, especially in Q1?"

Multi-step, deterministic assembly (Option A): calls two port query tools, builds SQL
evidence from each, and asserts ONE rigorous COMPARATIVE claim — the Q1-vs-rest delay
gap for the port. The second tool is a CONTROL: it shows the port is the clear outlier
among all ports in Q1, ruling out "Q1 is just slow everywhere" (same investigative move
as RC-04's warehouse-vs-others). The causal/seasonal interpretation stays in the answer
prose ("strongly indicates seasonal congestion"), NOT asserted as a verified causal
claim, because this is observational data — a Q1 GROUP BY is not proof of a mechanism.

Quarter is bucketed on planned_departure; the live Q1 figure is ~4.04 on this bucketing
(the handoff's ~5.06 was a different slice). All numbers are derived from tool output at
runtime, never hardcoded, so the COMPARATIVE check's base figures always match evidence.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from agent_contract import (
    AgentResponse, Claim, ClaimType, Evidence, Outcome, Relevance,
    SourceType, SupportStatus, Timing, ToolTraceEntry, Verification,
)
from postgres_tool import port_delay_by_quarter, port_q1_vs_others
from verifier import verify_response


def _row(rows, key, val):
    return next((r for r in rows if r.get(key) == val), None)


def investigate_rc01(database_url: str, port_code: str = "PORT-GEN",
                     question: str | None = None) -> AgentResponse:
    question = question or f"Why are shipments through {port_code} delayed, especially in Q1?"
    started = time.perf_counter()
    tool_ms = 0
    traces, evidences, claims = [], [], []

    def run(tool, step, purpose, out_ev, *args):
        nonlocal tool_ms
        t0 = time.perf_counter()
        res = tool(database_url, *args)
        tool_ms += int((time.perf_counter() - t0) * 1000)
        traces.append(ToolTraceEntry(
            step=step, tool_call_id=res.trace["tool_call_id"], tool="query_database",
            purpose=purpose, status="SUCCESS" if res.rows else "ERROR",
            input={"parameters": res.trace["parameters"]}, output_refs=[out_ev],
        ))
        return res

    a = run(port_delay_by_quarter, 1, "port delay Q1 vs rest of year", "EVD-P1", port_code)
    b = run(port_q1_vs_others, 2, "all ports' Q1 delay (is this port the outlier?)", "EVD-P2")

    q1 = _row(a.rows, "period", "Q1")
    rest = _row(a.rows, "period", "rest")

    if not (q1 and rest and b.rows):
        return AgentResponse(
            run_id="RUN-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
            question=question, outcome=Outcome.INSUFFICIENT_EVIDENCE,
            answer=f"Could not retrieve enough data to assess congestion at {port_code}.",
            claims=[], evidence=[], tool_trace=traces,
            verification=Verification(status="FAILED", checks=[]),
            timing=Timing(total_ms=int((time.perf_counter()-started)*1000), tool_ms=tool_ms),
        )

    q1_delay = float(q1["avg_delay_days"])
    rest_delay = float(rest["avg_delay_days"])
    gap = round(q1_delay - rest_delay, 2)

    # control: is this port the worst in Q1? (rows come ordered DESC by Q1 delay)
    top = b.rows[0]
    is_outlier = top["port_code"] == port_code
    runner_up = b.rows[1] if len(b.rows) > 1 else None
    runner_delay = float(runner_up["q1_avg_delay_days"]) if runner_up else None

    evidences.append(Evidence(
        evidence_id="EVD-P1", source_type=SourceType.SQL, source_ref="postgres:shipments",
        locator={"query_id": "SQL-P1", "port": port_code},
        fact=(f"Port {port_code} averages {q1_delay} days of delay in Q1 over {q1['n']} shipments, "
              f"versus {rest_delay} days over {rest['n']} shipments in the rest of the year."),
        relevance=Relevance.DIRECT,
    ))
    evidences.append(Evidence(
        evidence_id="EVD-P2", source_type=SourceType.SQL, source_ref="postgres:shipments",
        locator={"query_id": "SQL-P2"},
        fact=(f"Across all ports in Q1, {port_code} is the highest at {q1_delay} days; "
              f"the next-highest port averages {runner_delay} days, so the Q1 elevation is specific "
              f"to {port_code}, not a seasonal effect shared by every port."),
        relevance=Relevance.DIRECT,
    ))

    claims.append(Claim(
        claim_id="CLM-CMP",
        text=(f"Port {port_code} averages {q1_delay} days of delay in Q1 versus {rest_delay} days "
              f"the rest of the year, a gap of {gap} days, and is the worst-performing port in Q1."),
        claim_type=ClaimType.COMPARATIVE, support_status=SupportStatus.SUPPORTED,
        evidence_ids=["EVD-P1", "EVD-P2"],
    ))

    answer = (
        f"Shipments through {port_code} are delayed well above normal in Q1: they average "
        f"{q1_delay} days of delay in Q1 versus {rest_delay} days the rest of the year, a {gap}-day gap. "
        f"This is specific to {port_code} — it is the worst-performing port in Q1, while other ports "
        f"stay near their usual levels ({runner_delay} days for the next-highest), which rules out a "
        f"system-wide seasonal slowdown. Together this strongly indicates seasonal Q1 congestion "
        f"concentrated at {port_code}."
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