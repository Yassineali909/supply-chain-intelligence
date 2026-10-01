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

ROUTER_SYSTEM = """You classify a supply-chain question into exactly one investigation type.
Types:
- "shipment": about a specific shipment (e.g. "what happened to shipment SH-4921?")
- "supplier": about a supplier's performance (e.g. "why is supplier S07 chronically late?")
- "out_of_scope": anything else this system cannot investigate.
Respond with ONLY JSON: {"type": "shipment|supplier|out_of_scope"}. No prose."""


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*?\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def _deterministic_type(question: str) -> str:
    if SHIPMENT_RE.search(question):
        return "shipment"
    if SUPPLIER_RE.search(question) or "supplier" in question.lower():
        return "supplier"
    return "out_of_scope"


def classify(llm_call, question: str) -> str:
    det = _deterministic_type(question)
    raw = llm_call(ROUTER_SYSTEM, f"Question: {question}")
    t = _extract_json(raw).get("type", "")
    if t not in ("shipment", "supplier", "out_of_scope"):
        return det
    if det in ("shipment", "supplier") and t == "out_of_scope":
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
        return investigate_with_planner(llm_call, database_url, document_root, code, question)

    if qtype == "supplier":
        from rc02 import investigate_rc02
        m = SUPPLIER_RE.search(question)
        code = m.group(0) if m else "S00"
        return investigate_rc02(database_url, code, question)

    return _refusal(question)
