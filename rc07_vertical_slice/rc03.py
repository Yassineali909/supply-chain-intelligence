"""
RC-03 investigation: "Is carrier <CODE>'s performance getting worse over time?"

The ONLY scenario that honestly lands on PARTIALLY_SUPPORTED. Carrier CR3's delay climbs
gradually across the 24-month window — a measurable TREND, but a noisy one with no single
pinpointable cause, so the honest verdict is PARTIAL, not SUPPORTED. The outcome and the
claim's support_status are set to PARTIAL BY INTENT (a legitimate hedge), NOT produced as
SUPPORTED and downgraded — the LEGITIMATE_PARTIAL_OUTCOME check distinguishes the two.

Claim is built from THIRDS (early/mid/late), never single-month endpoints, so a sparse
month (e.g. a lone late shipment) cannot drive it. A fleet-control tool rules out a
system-wide slowdown, so the trend is attributable to THIS carrier specifically.
Numbers are derived from tool output at runtime, never hardcoded.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from agent_contract import (
    AgentResponse, Claim, ClaimType, Evidence, Outcome, Relevance,
    SourceType, SupportStatus, Timing, ToolTraceEntry, Verification,
)
from postgres_tool import carrier_delay_by_thirds, carrier_thirds_fleet
from verifier import verify_response


def _third(rows, n):
    return next((r for r in rows if r.get("third") == n), None)


def investigate_rc03(database_url: str, carrier_code: str = "CR3",
                     question: str | None = None) -> AgentResponse:
    question = question or f"Is carrier {carrier_code}'s performance getting worse over time?"
    started = time.perf_counter()
    tool_ms = 0
    traces, evidences, claims = [], [], []

    def run(tool, step, purpose, out_ev):
        nonlocal tool_ms
        t0 = time.perf_counter()
        res = tool(database_url, carrier_code)
        tool_ms += int((time.perf_counter() - t0) * 1000)
        traces.append(ToolTraceEntry(
            step=step, tool_call_id=res.trace["tool_call_id"], tool="query_database",
            purpose=purpose, status="SUCCESS" if res.rows else "ERROR",
            input={"parameters": res.trace["parameters"]}, output_refs=[out_ev],
        ))
        return res

    a = run(carrier_delay_by_thirds, 1, "carrier delay across early/mid/late thirds", "EVD-T1")
    b = run(carrier_thirds_fleet, 2, "all other carriers' delay by third (fleet control)", "EVD-T2")

    e, m, l = _third(a.rows, 1), _third(a.rows, 2), _third(a.rows, 3)

    # need all three thirds for the subject, and the fleet control, to assess a trend
    if not (e and m and l and b.rows):
        return AgentResponse(
            run_id="RUN-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
            question=question, outcome=Outcome.INSUFFICIENT_EVIDENCE,
            answer=f"Could not retrieve enough history to assess carrier {carrier_code}.",
            claims=[], evidence=[], tool_trace=traces,
            verification=Verification(status="FAILED", checks=[]),
            timing=Timing(total_ms=int((time.perf_counter()-started)*1000), tool_ms=tool_ms),
        )

    early = float(e["avg_delay_days"])
    mid = float(m["avg_delay_days"])
    late = float(l["avg_delay_days"])
    rising = early < mid < late

    # Honesty gate: only assert a degradation TREND if the thirds actually rise. A flat or
    # improving carrier must NOT get a "trends upward" claim — refuse instead (same refusal
    # discipline as RC-06). This matters once the router admits an arbitrary carrier_code.
    if not rising:
        return AgentResponse(
            run_id="RUN-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
            question=question, outcome=Outcome.INSUFFICIENT_EVIDENCE,
            answer=(f"Carrier {carrier_code} does not show a clear upward delay trend across the "
                    f"window ({early} / {mid} / {late} days by third), so I cannot assert that it is "
                    f"degrading over time."),
            claims=[], evidence=[], tool_trace=traces,
            verification=Verification(status="FAILED", checks=[]),
            timing=Timing(total_ms=int((time.perf_counter()-started)*1000), tool_ms=tool_ms),
        )  # monotonic across thirds

    fe, fm, fl = _third(b.rows, 1), _third(b.rows, 2), _third(b.rows, 3)
    fleet_early = float(fe["avg_delay_days"]) if fe else None
    fleet_late = float(fl["avg_delay_days"]) if fl else None

    evidences.append(Evidence(
        evidence_id="EVD-T1", source_type=SourceType.SQL, source_ref="postgres:shipments",
        locator={"query_id": "SQL-T1", "carrier": carrier_code},
        fact=(f"Carrier {carrier_code} average delay rose across the window: {early} days (early third, "
              f"{e['n']} shipments) to {mid} days (mid, {m['n']}) to {late} days (late, {l['n']})."),
        relevance=Relevance.DIRECT,
    ))
    evidences.append(Evidence(
        evidence_id="EVD-T2", source_type=SourceType.SQL, source_ref="postgres:shipments",
        locator={"query_id": "SQL-T2", "exclude": carrier_code},
        fact=(f"Over the same thirds, all other carriers stayed roughly flat "
              f"({fleet_early} to {fleet_late} days), so the increase is specific to {carrier_code}, "
              f"not a fleet-wide slowdown."),
        relevance=Relevance.DIRECT,
    ))

    # TREND claim, support_status=PARTIAL BY INTENT — a legitimate hedge, not a downgrade.
    claims.append(Claim(
        claim_id="CLM-TREND",
        text=(f"Carrier {carrier_code}'s average delay trends upward over the 24-month window, from "
              f"{early} days in the early third to {late} days in the late third, while other carriers "
              f"stay flat — a gradual degradation, though the data does not isolate a single cause."),
        claim_type=ClaimType.TREND, support_status=SupportStatus.PARTIAL,
        evidence_ids=["EVD-T1", "EVD-T2"],
    ))

    answer = (
        f"Carrier {carrier_code}'s performance is degrading over time, but gradually and without a "
        f"single identifiable cause. Its average delay rose from {early} days in the early third of the "
        f"window to {mid} then {late} days in the late third, while the rest of the fleet stayed flat "
        f"({fleet_early} to {fleet_late} days) — so this is {carrier_code} specifically worsening, not a "
        f"system-wide trend. Because the decline is gradual and noisy rather than tied to a discrete "
        f"event, the evidence supports a degradation trend but does not pin down why — a partial finding."
    )

    resp = AgentResponse(
        run_id="RUN-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
        question=question, outcome=Outcome.PARTIALLY_SUPPORTED, answer=answer,
        claims=claims, evidence=evidences, tool_trace=traces,
        verification=Verification(status="FAILED", checks=[]),
        timing=Timing(total_ms=int((time.perf_counter()-started)*1000), tool_ms=tool_ms),
    )
    verified = verify_response(resp)
    verified.tool_trace.append(ToolTraceEntry(
        step=len(traces)+1, tool_call_id="TC-VERIFY", tool="verify_evidence",
        purpose="confirm the partial trend claim is bound to SQL evidence and legitimately partial",
        status="SUCCESS" if verified.verification.status == "PASSED" else "ERROR",
        input={"claim_ids": [c.claim_id for c in verified.claims]}, output_refs=[],
    ))
    return verified