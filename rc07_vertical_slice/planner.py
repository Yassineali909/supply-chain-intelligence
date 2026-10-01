"""
LangGraph-style LLM planner for RC-07 (Option A: LLM routes, code assembles evidence).

The LLM decides WHICH tool to call next; it never writes facts or claims. Each step it
sees the question + a compact summary of what's gathered, and returns one decision:
query_database | search_documents | finish. Code executes the tool (reusing the
deterministic tools), records the observation, and loops. On finish (or step cap) a
deterministic assembler builds the AgentResponse and the hardened verifier runs.

Trust boundary: the model controls CONTROL FLOW; deterministic code controls EVIDENCE.
A 3B router can misbehave, so decisions are parsed strictly with safe fallbacks and the
loop is capped.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone

from agent_contract import (
    AgentResponse, Claim, ClaimType, Evidence, Outcome, Relevance,
    SourceType, SupportStatus, Timing, ToolTraceEntry, Verification,
)
from postgres_tool import query_shipment
from document_store import search_documents
from verifier import verify_response


VALID_ACTIONS = {"query_database", "search_documents", "finish"}
MAX_STEPS = 6

PLANNER_SYSTEM = """You are the router for a supply-chain investigation agent.
Your ONLY job is to choose the next tool to call. You do NOT write answers or facts.

Available tools:
- query_database: fetch the shipment's record (dates, delay, route, port, carrier).
- search_documents: find operational documents (incident reports) about the shipment.
- finish: stop investigating; enough has been gathered.

Rules:
- Call query_database before search_documents (you need the shipment first).
- After you have the shipment record AND searched documents, choose finish.
- Respond with ONLY a JSON object: {"action": "<tool>", "reason": "<short reason>"}
- No prose, no markdown fences. Just the JSON object.
"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    m = re.search(r"\{.*?\}", text, flags=re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def _available_actions(gathered: dict) -> list[str]:
    """Only offer actions that make sense given what's already gathered. Constraining the
    action space by state stops a weak router from repeating a done step forever."""
    have_shipment = gathered.get("shipment") is not None
    have_docs = gathered.get("docs_searched", False)
    if not have_shipment:
        return ["query_database"]
    if not have_docs:
        return ["search_documents", "finish"]
    return ["finish"]


def _decide(llm_call, question: str, gathered: dict) -> str:
    """Choose the next action, constrained to what's valid in the current state.

    If only one action is possible, don't ask the model at all — it can't add value and
    a weak 3B router might get it wrong. This guarantees forward progress and is why a
    router that always says 'query_database' can no longer loop.
    """
    available = _available_actions(gathered)
    if len(available) == 1:
        return available[0]

    state_summary = {
        "have_shipment": gathered.get("shipment") is not None,
        "have_documents": gathered.get("docs_searched", False),
    }
    user = (
        f"Question: {question}\n"
        f"Gathered so far: {json.dumps(state_summary)}\n"
        f"Available actions right now: {available}\n"
        f'Choose ONE available action. Respond with JSON: {{"action": "...", "reason": "..."}}'
    )
    raw = llm_call(PLANNER_SYSTEM, user)
    decision = _extract_json(raw)
    action = decision.get("action", "")
    if action not in available:
        return available[0]
    return action


import re as _re


def _extract_cause(doc_text: str):
    """Derive the delay cause from the retrieved document's OWN text, so the answer can
    never contradict its evidence (the hardcoded-cause bug the LLM judge caught)."""
    for pat in (r"affected by (.+?),", r"records (.+?) affecting", r"we note (.+?)\."):
        m = _re.search(pat, doc_text, _re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _assemble(question, shipment_code, gathered, started, tool_ms) -> AgentResponse:
    traces = gathered["traces"]
    row = gathered.get("shipment")
    evidences = []
    claims = []

    if row is None:
        return AgentResponse(
            run_id="RUN-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
            question=question, outcome=Outcome.INSUFFICIENT_EVIDENCE,
            answer=f"I could not find shipment {shipment_code} in the operational database.",
            claims=[], evidence=[], tool_trace=traces,
            verification=Verification(status="FAILED", checks=[]),
            timing=Timing(total_ms=int((time.perf_counter()-started)*1000), tool_ms=tool_ms),
        )

    evidences.append(Evidence(
        evidence_id="EVD-001", source_type=SourceType.SQL, source_ref="postgres:shipments",
        locator={"query_id": "SQL-0001", "row_keys": [shipment_code]},
        fact=(f"Shipment {shipment_code} has planned arrival {row['planned_arrival']}, "
              f"actual arrival {row['actual_arrival']}, and recorded delay {row['delay_days']} days."),
        relevance=Relevance.DIRECT,
    ))
    claims.append(Claim(
        claim_id="CLM-001", text=f"{shipment_code} arrived {row['delay_days']} days late.",
        claim_type=ClaimType.NUMERIC, support_status=SupportStatus.SUPPORTED,
        evidence_ids=["EVD-001"],
    ))

    direct_doc = gathered.get("direct_doc")
    if direct_doc is not None:
        doc_id = direct_doc["doc_id"]
        _cause = _extract_cause(str(direct_doc.get("text", ""))) or "an operational incident"
        evidences.append(Evidence(
            evidence_id="EVD-002", source_type=SourceType.DOCUMENT, source_ref=doc_id,
            locator={"chunk_id": f"{doc_id}:C01"},
            fact=str(direct_doc.get("text", "")).strip(),
            relevance=Relevance.DIRECT,
        ))
        claims.append(Claim(
            claim_id="CLM-002",
            text=(f"The delay was caused by {_cause}; the incident report identifies "
                  f"{direct_doc.get('metadata', {}).get('incident_code', 'the incident')} as the event."),
            claim_type=ClaimType.CAUSAL, support_status=SupportStatus.SUPPORTED,
            evidence_ids=["EVD-002"],
        ))
        answer = (f"Shipment {shipment_code} arrived {row['delay_days']} days late. "
                  f"The available incident report attributes the delay to {_cause}.")
        outcome = Outcome.SUPPORTED
    else:
        answer = (f"Shipment {shipment_code} was delayed by {row['delay_days']} days, "
                  "but I could not find a document that establishes why.")
        outcome = Outcome.INSUFFICIENT_EVIDENCE

    resp = AgentResponse(
        run_id="RUN-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
        question=question, outcome=outcome, answer=answer,
        claims=claims, evidence=evidences, tool_trace=traces,
        verification=Verification(status="FAILED", checks=[]),
        timing=Timing(total_ms=int((time.perf_counter()-started)*1000), tool_ms=tool_ms),
    )
    verified = verify_response(resp)
    verified.tool_trace.append(ToolTraceEntry(
        step=len(traces)+1, tool_call_id="TC-VERIFY", tool="verify_evidence",
        purpose="check claims are bound to tool-produced evidence",
        status="SUCCESS" if verified.verification.status == "PASSED" else "ERROR",
        input={"claim_ids": [c.claim_id for c in verified.claims]}, output_refs=[],
    ))
    verified.timing = Timing(total_ms=int((time.perf_counter()-started)*1000), tool_ms=tool_ms)
    return verified


def investigate_with_planner(llm_call, database_url, document_root,
                             shipment_code="SH-4921",
                             question="What happened to shipment SH-4921?") -> AgentResponse:
    started = time.perf_counter()
    tool_ms = 0
    gathered = {"shipment": None, "docs_searched": False, "direct_doc": None, "traces": []}
    step = 0

    while step < MAX_STEPS:
        action = _decide(llm_call, question, gathered)
        if action == "finish":
            break

        if action == "query_database":
            t0 = time.perf_counter()
            sql = query_shipment(database_url, shipment_code)
            tool_ms += int((time.perf_counter()-t0)*1000)
            gathered["shipment"] = sql.rows[0] if sql.rows else None
            gathered["traces"].append(ToolTraceEntry(
                step=len(gathered["traces"])+1, tool_call_id=sql.trace.get("tool_call_id","TC-SQL"),
                tool="query_database", purpose="retrieve shipment record",
                status="SUCCESS" if sql.rows else "ERROR",
                input={"parameters": {"shipment_code": shipment_code}},
                output_refs=["EVD-001"] if sql.rows else [],
            ))
            if not sql.rows:
                break

        elif action == "search_documents":
            t0 = time.perf_counter()
            docs, doc_trace, _ = search_documents(document_root, shipment_code)
            tool_ms += int((time.perf_counter()-t0)*1000)
            gathered["docs_searched"] = True
            direct = next((d for d in docs if str(d.get("metadata",{}).get("relevance","")).upper()
                           == Relevance.DIRECT.value), None)
            gathered["direct_doc"] = direct
            gathered["traces"].append(ToolTraceEntry(
                step=len(gathered["traces"])+1, tool_call_id=doc_trace.get("tool_call_id","TC-DOC"),
                tool="search_documents", purpose=doc_trace.get("purpose","find shipment documents"),
                status="SUCCESS" if docs else "ERROR",
                input=doc_trace.get("input", {"shipment_code": shipment_code}),
                output_refs=["EVD-002"] if direct else [],
            ))

        step += 1

    return _assemble(question, shipment_code, gathered, started, tool_ms)
