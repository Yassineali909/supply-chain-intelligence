"""
Top-level investigation router: classify a question and dispatch to the right
investigation (RC-07 shipment, RC-02 supplier), or refuse if out of scope.

LLM classifies (agentic), with a DETERMINISTIC entity-pattern fallback so a weak 3B
model can't misroute. Out-of-scope -> INSUFFICIENT_EVIDENCE refusal, extending the
honesty principle to the routing layer: the agent won't investigate a question it has
no tools for.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from agent_contract import AgentResponse, Outcome, Verification, Timing

SHIPMENT_RE = re.compile(r"\bSH-\d+\b")
SUPPLIER_RE = re.compile(r"\bS\d{2,}\b")
WAREHOUSE_RE = re.compile(r"\bWH-\d+\b")
WAREHOUSE_KEYWORDS = ("warehouse", "deliveries from", "outbound")

ROUTER_SYSTEM = """You classify a supply-chain question into exactly one investigation type.
Types:
- "shipment": about a specific shipment (e.g. "what happened to shipment SH-4921?")
- "supplier": about a supplier's performance (e.g. "why is supplier S07 chronically late?")
- "impact": which customers are affected by a port/route disruption (co-exposure).
- "out_of_scope": anything else this system cannot investigate.
Respond with ONLY JSON: {"type": "shipment|supplier|impact|out_of_scope"}. No prose."""


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*?\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


GRAPH_KEYWORDS = ("congestion", "port", "affected", "co-exposed", "cascade",
                  "disruption", "impact", "which customers")


def _deterministic_type(question: str) -> str:
    q = question.lower()
    # graph/impact questions first (they may also mention a port like PORT-GEN)
    if any(k in q for k in GRAPH_KEYWORDS) and "customer" in q:
        return "impact"
    if WAREHOUSE_RE.search(question) or any(k in q for k in WAREHOUSE_KEYWORDS):
        return "warehouse"
    if SHIPMENT_RE.search(question):
        return "shipment"
    if SUPPLIER_RE.search(question) or "supplier" in question.lower():
        return "supplier"
    return "out_of_scope"


def _has_strong_pattern(question: str):
    """Return a type if the question contains an UNAMBIGUOUS entity code, else None.
    A clear code (WH-2, SH-4921) beats the LLM's guess — a weak model should not override
    an unambiguous signal (same discipline as constraining the tool-routing loop)."""
    if WAREHOUSE_RE.search(question):
        return "warehouse"
    if SHIPMENT_RE.search(question):
        return "shipment"
    return None


def classify(llm_call, question: str) -> str:
    det = _deterministic_type(question)
    # Unambiguous entity code wins over everything, including the LLM.
    strong = _has_strong_pattern(question)
    if strong:
        return strong
    raw = llm_call(ROUTER_SYSTEM, f"Question: {question}")
    t = _extract_json(raw).get("type", "")
    if t not in ("shipment", "supplier", "impact", "warehouse", "out_of_scope"):
        return det
    if det in ("shipment", "supplier", "impact", "warehouse") and t == "out_of_scope":
        return det
    return t


def _refusal(question: str) -> AgentResponse:
    return AgentResponse(
        run_id="RUN-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
        question=question, outcome=Outcome.INSUFFICIENT_EVIDENCE,
        answer=("This question is outside what I can investigate. I can look into a specific "
                "shipment (e.g. 'what happened to SH-4921?') or a supplier's performance "
                "(e.g. 'why is S07 late?')."),
        claims=[], evidence=[], tool_trace=[],
        verification=Verification(status="FAILED", checks=[]),
        timing=Timing(total_ms=0, tool_ms=0),
    )


def investigate(llm_call, database_url, document_root, question: str) -> AgentResponse:
    qtype = classify(llm_call, question)

    if qtype == "shipment":
        from planner import investigate_with_planner
        m = SHIPMENT_RE.search(question)
        code = m.group(0) if m else "SH-0000"
        resp = investigate_with_planner(llm_call, database_url, document_root, code, question)
    elif qtype == "supplier":
        from rc02 import investigate_rc02
        m = SUPPLIER_RE.search(question)
        code = m.group(0) if m else "S00"
        resp = investigate_rc02(database_url, code, question)
    elif qtype == "impact":
        from rc05 import investigate_rc05
        resp = investigate_rc05(question)
    elif qtype == "warehouse":
        from rc04 import investigate_rc04
        m = WAREHOUSE_RE.search(question)
        code = m.group(0) if m else "WH-2"
        resp = investigate_rc04(database_url, code, question)
    else:
        resp = _refusal(question)

    try:
        from run_logger import log_run
        log_run(resp, qtype)
    except Exception:
        pass
    return resp
