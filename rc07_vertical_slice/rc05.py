"""
RC-05 investigation: multi-hop co-exposure through a shared disrupted route.

Question shape: "which customers are affected by the port congestion through suppliers
sharing the disrupted route?" This is the GRAPH showcase — the answer requires traversing
Customer <- Shipment <- Supplier across SHARED route/port nodes, a variable-depth
reachability question SQL expresses awkwardly.

Deterministic assembly (Option A): calls the graph tools, builds GRAPH evidence, and
asserts a RELATIONSHIP claim (how many customers are co-exposed, within the known
problem-network). Scoped honestly to the RC-05 supplier network the scenario defines.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from agent_contract import (
    AgentResponse, Claim, ClaimType, Evidence, Outcome, Relevance,
    SourceType, SupportStatus, Timing, ToolTraceEntry, Verification,
)
from graph_tool import coexposure, per_supplier_reach
from verifier import verify_response

RC05_NETWORK = ["S07", "S11", "S19", "S23"]
RC05_ROUTE = "RT-04"
RC05_PORT = "PORT-GEN"


def investigate_rc05(question: str | None = None, *, route=RC05_ROUTE,
                     suppliers=None, port=RC05_PORT, **conn) -> AgentResponse:
    suppliers = suppliers or RC05_NETWORK
    question = question or (f"Which customers are affected by congestion at {port} "
                            f"through suppliers sharing route {route}?")
    started = time.perf_counter()
    tool_ms = 0
    traces, evidences, claims = [], [], []

    def run(tool, step, purpose, out_ev):
        nonlocal tool_ms
        t0 = time.perf_counter()
        res = tool(route, suppliers, **conn)
        tool_ms += int((time.perf_counter() - t0) * 1000)
        traces.append(ToolTraceEntry(
            step=step, tool_call_id=res.trace["tool_call_id"], tool="graph_query",
            purpose=purpose, status="SUCCESS" if res.rows else "ERROR",
            input={"route": route, "suppliers": suppliers}, output_refs=[out_ev],
        ))
        return res

    g1 = run(coexposure, 1, "count customers co-exposed through the shared route", "EVD-G1")
    g2 = run(per_supplier_reach, 2, "per-supplier customer reach on the shared route", "EVD-G2")

    if not g1.rows or g1.rows[0].get("co_exposed_customers") is None:
        return AgentResponse(
            run_id="RUN-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
            question=question, outcome=Outcome.INSUFFICIENT_EVIDENCE,
            answer="Could not determine the co-exposure network from the graph.",
            claims=[], evidence=[], tool_trace=traces,
            verification=Verification(status="FAILED", checks=[]),
            timing=Timing(total_ms=int((time.perf_counter()-started)*1000), tool_ms=tool_ms),
        )

    co = g1.rows[0]["co_exposed_customers"]
    max_n = g1.rows[0]["max_network_suppliers"]
    per = {r["supplier"]: r["customers"] for r in g2.rows}

    evidences.append(Evidence(
        evidence_id="EVD-G1", source_type=SourceType.GRAPH, source_ref="neo4j:coexposure",
        locator={"query_id": "GRAPH-1", "route": route, "suppliers": suppliers},
        fact=(f"Traversing the graph, {co} customers are co-exposed through route {route} "
              f"(served by more than one of suppliers {', '.join(suppliers)}; up to {max_n} "
              f"of them per customer)."),
        relevance=Relevance.DIRECT,
    ))
    evidences.append(Evidence(
        evidence_id="EVD-G2", source_type=SourceType.GRAPH, source_ref="neo4j:per_supplier",
        locator={"query_id": "GRAPH-2", "route": route},
        fact="Per-supplier reach on the route: " +
             "; ".join(f"{s} serves {per.get(s, 0)} customers" for s in suppliers) + ".",
        relevance=Relevance.DIRECT,
    ))

    claims.append(Claim(
        claim_id="CLM-REL",
        text=(f"{co} customers are co-exposed to a disruption on route {route}, because "
              f"they are served by multiple suppliers in the network {', '.join(suppliers)} "
              f"that all route through {port}."),
        claim_type=ClaimType.RELATIONSHIP, support_status=SupportStatus.SUPPORTED,
        evidence_ids=["EVD-G1", "EVD-G2"],
    ))

    answer = (
        f"Congestion at {port} does not hit one supplier in isolation. {co} customers are "
        f"co-exposed on route {route}: each is served by more than one of the suppliers "
        f"{', '.join(suppliers)}, which all pass through {port}. A disruption there therefore "
        f"cascades to those customers through multiple suppliers at once."
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
        purpose="check the relationship claim is bound to graph evidence",
        status="SUCCESS" if verified.verification.status == "PASSED" else "ERROR",
        input={"claim_ids": [c.claim_id for c in verified.claims]}, output_refs=[],
    ))
    return verified
