"""
Supplier-ranking investigation: "Which supplier is the worst / the biggest problem?"

A NEW capability (not a planted RC scenario): surveys ALL suppliers and ranks them, where
every prior supplier investigation answered about a NAMED supplier. Motivated by the
held-out boundary (HO-supplier-noentity) — the agent used to refuse this because no entity
was named; now it can answer.

HONEST metric: ranks by avg delay on CLEAN routes (congested port excluded), so a supplier
is judged on its OWN reliability, not blamed for bad routing. Ranking by RAW delay would
unfairly include route-confounded suppliers (the RC-05 shared-route group rides high on raw
delay alone). The claim is COMPARATIVE — worst vs next-worst, with the derived gap — so it
reuses the mutation-tested COMPARATIVE_CLAIM_MATCHES_SQL check (no new verifier work). The
"worst" is scoped honestly in prose: worst BY THIS METRIC, not an unqualified absolute.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from agent_contract import (
    AgentResponse, Claim, ClaimType, Evidence, Outcome, Relevance,
    SourceType, SupportStatus, Timing, ToolTraceEntry, Verification,
)
from postgres_tool import supplier_ranking_clean
from verifier import verify_response


def investigate_supplier_ranking(database_url: str, question: str | None = None,
                                 *, top_n: int = 5) -> AgentResponse:
    question = question or "Which supplier is the worst?"
    started = time.perf_counter()
    tool_ms = 0
    traces, evidences, claims = [], [], []

    t0 = time.perf_counter()
    res = supplier_ranking_clean(database_url, top_n=top_n)
    tool_ms += int((time.perf_counter() - t0) * 1000)
    traces.append(ToolTraceEntry(
        step=1, tool_call_id=res.trace["tool_call_id"], tool="query_database",
        purpose="rank all suppliers by clean-route avg delay (de-confounded)",
        status="SUCCESS" if res.rows else "ERROR",
        input={"parameters": res.trace["parameters"]}, output_refs=["EVD-RANK"],
    ))

    # need at least two suppliers to assert a worst-vs-next-worst comparison
    if len(res.rows) < 2:
        return AgentResponse(
            run_id="RUN-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
            question=question, outcome=Outcome.INSUFFICIENT_EVIDENCE,
            answer="Could not retrieve enough suppliers to produce a ranking.",
            claims=[], evidence=[], tool_trace=traces,
            verification=Verification(status="FAILED", checks=[]),
            timing=Timing(total_ms=int((time.perf_counter()-started)*1000), tool_ms=tool_ms),
        )

    worst = res.rows[0]
    runner = res.rows[1]
    worst_code = worst["supplier_code"]
    worst_delay = float(worst["clean_avg_delay_days"])
    runner_code = runner["supplier_code"]
    runner_delay = float(runner["clean_avg_delay_days"])
    gap = round(worst_delay - runner_delay, 2)

    # full ranking text for the evidence (keeps the whole field visible)
    ranking_str = "; ".join(
        f"{r['supplier_code']} {float(r['clean_avg_delay_days'])} days ({r['shipment_count']} shipments)"
        for r in res.rows
    )

    evidences.append(Evidence(
        evidence_id="EVD-RANK", source_type=SourceType.SQL, source_ref="postgres:shipments",
        locator={"query_id": "SQL-RANK", "metric": "clean_route_avg_delay"},
        fact=(f"Suppliers ranked by average delay on clean routes (congested port excluded), "
              f"worst first: {ranking_str}."),
        relevance=Relevance.DIRECT,
    ))

    claims.append(Claim(
        claim_id="CLM-RANK",
        text=(f"Supplier {worst_code} is the worst by de-confounded clean-route delay, averaging "
              f"{worst_delay} days versus {runner_delay} days for the next-worst ({runner_code}), "
              f"a gap of {gap} days."),
        claim_type=ClaimType.COMPARATIVE, support_status=SupportStatus.SUPPORTED,
        evidence_ids=["EVD-RANK"],
    ))

    answer = (
        f"By de-confounded reliability — average delay on clean routes, which excludes the "
        f"congested port so suppliers are judged on their own performance rather than their "
        f"routing — supplier {worst_code} is the worst, averaging {worst_delay} days. That is "
        f"well clear of the next-worst, {runner_code} at {runner_delay} days (a {gap}-day gap). "
        f"Note this uses clean-route delay deliberately: ranking by raw delay would unfairly "
        f"penalise suppliers that happen to route through the congested port. The full ranking "
        f"is in the evidence."
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
        purpose="check the ranking's worst-vs-next-worst figures against SQL evidence",
        status="SUCCESS" if verified.verification.status == "PASSED" else "ERROR",
        input={"claim_ids": [c.claim_id for c in verified.claims]}, output_refs=[],
    ))
    return verified
