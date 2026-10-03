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
PORT_RE = re.compile(r"\bPORT-[A-Z]+\b")
PORT_KEYWORDS = ("port", "congestion", "congested")
CARRIER_RE = re.compile(r"\bCR\d+\b")
CARRIER_KEYWORDS = ("carrier",)

ROUTER_SYSTEM = """You classify a supply-chain question into exactly one investigation type.
Types:
- "shipment": about a specific shipment (e.g. "what happened to shipment SH-4921?")
- "supplier": about a supplier's performance (e.g. "why is supplier S07 chronically late?")
- "impact": which customers are affected by a port/route disruption (co-exposure).
- "port": delays through a specific port / seasonal port congestion, with NO mention of affected customers (e.g. "why are shipments through PORT-GEN delayed in Q1?").
- "carrier": whether a carrier is degrading in performance over time (e.g. "is carrier CR3 getting worse?").
- "out_of_scope": anything else this system cannot investigate.
Respond with ONLY JSON: {"type": "shipment|supplier|impact|port|carrier|out_of_scope"}. No prose."""


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
    # a PORT question WITHOUT customers is a port-delay investigation (RC-01), not graph.
    # MUST stay AFTER the impact branch above (RC-05 owns port+customer questions).
    if PORT_RE.search(question) or any(k in q for k in PORT_KEYWORDS):
        return "port"
    if WAREHOUSE_RE.search(question) or any(k in q for k in WAREHOUSE_KEYWORDS):
        return "warehouse"
    if CARRIER_RE.search(question) or any(k in q for k in CARRIER_KEYWORDS):
        return "carrier"
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
    if CARRIER_RE.search(question):
        return "carrier"
    return None


def classify(llm_call, question: str) -> str:
    det = _deterministic_type(question)
    # Unambiguous entity code wins over everything, including the LLM.
    strong = _has_strong_pattern(question)
    if strong:
        return strong
    raw = llm_call(ROUTER_SYSTEM, f"Question: {question}")
    t = _extract_json(raw).get("type", "")
    if t not in ("shipment", "supplier", "impact", "port", "carrier", "warehouse", "out_of_scope"):
        return det
    if det in ("shipment", "supplier", "impact", "port", "carrier", "warehouse") and t == "out_of_scope":
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


def _refusal_no_entity(question: str, kind: str, example: str) -> AgentResponse:
    """Routed to a port/warehouse/carrier investigation by KEYWORD, but no specific entity
    was named. Refuse rather than silently default to the planted entity — answering about
    the wrong entity is confidently-wrong output."""
    return AgentResponse(
        run_id="RUN-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
        question=question, outcome=Outcome.INSUFFICIENT_EVIDENCE,
        answer=(f"This looks like a {kind} question, but I could not identify a specific "
                f"{kind} to investigate. Please name one (e.g. {example})."),
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
        m = WAREHOUSE_RE.search(question)
        if not m:
            resp = _refusal_no_entity(question, "warehouse", "WH-2")
        else:
            from rc04 import investigate_rc04
            resp = investigate_rc04(database_url, m.group(0), question)
    elif qtype == "port":
        m = PORT_RE.search(question)
        if not m:
            resp = _refusal_no_entity(question, "port", "PORT-GEN")
        else:
            from rc01 import investigate_rc01
            resp = investigate_rc01(database_url, m.group(0), question)
    elif qtype == "carrier":
        m = CARRIER_RE.search(question)
        if not m:
            resp = _refusal_no_entity(question, "carrier", "CR3")
        else:
            from rc03 import investigate_rc03
            resp = investigate_rc03(database_url, m.group(0), question)
    else:
        resp = _refusal(question)

    try:
        from run_logger import log_run
        log_run(resp, qtype)
    except Exception:
        pass
    return resp
