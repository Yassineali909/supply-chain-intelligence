"""
RC-04 warehouse stage-localization tests. Mock the two warehouse query tools (no live DB).
Pins the trap logic: the investigation must localize the delay to the outbound/warehouse
stage and produce a verified COMPARATIVE claim, plus router routing of warehouse questions.
"""
import rc04
import router
from postgres_tool import SQLToolResult
from agent_contract import Outcome, ClaimType


def _inout(db, warehouse_code, **k):
    return SQLToolResult("EVD-W1", "SQL-W1", [
        {"period": "non_peak", "n": 833, "inbound_delay_days": 1.92, "outbound_delay_days": 0.69},
        {"period": "peak", "n": 146, "inbound_delay_days": 1.34, "outbound_delay_days": 1.74},
    ], {"tool_call_id": "TC-W1", "parameters": {"warehouse_code": warehouse_code}})


def _vs_others(db, **k):
    return SQLToolResult("EVD-W2", "SQL-W2", [
        {"warehouse_code": "WH-2", "inbound_delay_days": 1.34, "outbound_delay_days": 1.74},
        {"warehouse_code": "WH-3", "inbound_delay_days": 1.43, "outbound_delay_days": 0.57},
    ], {"tool_call_id": "TC-W2", "parameters": {}})


def test_rc04_localizes_to_warehouse_stage(monkeypatch):
    monkeypatch.setattr(rc04, "warehouse_inbound_vs_outbound", _inout)
    monkeypatch.setattr(rc04, "warehouse_vs_others_peak", _vs_others)
    resp = rc04.investigate_rc04("fake://db", "WH-2")
    assert resp.outcome == Outcome.SUPPORTED
    assert resp.verification.status == "PASSED"
    assert resp.claims[0].claim_type == ClaimType.COMPARATIVE
    # the distinctive RC-04 reasoning: rules out the supplier
    assert "not a supplier problem" in resp.answer
    assert [t.tool for t in resp.tool_trace] == ["query_database", "query_database", "verify_evidence"]


def test_rc04_no_peak_data_yields_insufficient(monkeypatch):
    monkeypatch.setattr(rc04, "warehouse_inbound_vs_outbound",
        lambda db, warehouse_code, **k: SQLToolResult("EVD-W1", "SQL-W1", [], {"tool_call_id": "TC-W1", "parameters": {}}))
    monkeypatch.setattr(rc04, "warehouse_vs_others_peak", _vs_others)
    resp = rc04.investigate_rc04("fake://db", "WH-2")
    assert resp.outcome == Outcome.INSUFFICIENT_EVIDENCE


def test_router_routes_warehouse_questions():
    # unambiguous WH- code must win over any LLM guess
    wrong_llm = lambda s, u: '{"type":"shipment"}'
    assert router.classify(wrong_llm, "Why are deliveries from WH-2 slow?") == "warehouse"
    # keyword-based routing when no code present
    good = lambda s, u: '{"type":"warehouse"}'
    assert router.classify(good, "Why are warehouse deliveries slow during the peak?") == "warehouse"
