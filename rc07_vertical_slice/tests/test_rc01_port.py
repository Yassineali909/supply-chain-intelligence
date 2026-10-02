"""
RC-01 port-congestion tests. Mock the two port query tools (no live DB).
Pins: the investigation produces a verified COMPARATIVE claim on the Q1-vs-rest gap,
refuses when quarter data is missing, and the router disambiguates a port-DELAY question
(RC-01) from a port-CUSTOMER-impact question (RC-05/graph).
"""
import rc01
import router
from postgres_tool import SQLToolResult
from agent_contract import Outcome, ClaimType


def _by_quarter(db, port_code, **k):
    # mirrors the live PORT-GEN numbers: Q1 4.04 over 249, rest 1.81 over 774
    return SQLToolResult("EVD-P1", "SQL-P1", [
        {"period": "Q1",   "n": 249, "avg_delay_days": 4.04},
        {"period": "rest", "n": 774, "avg_delay_days": 1.81},
    ], {"tool_call_id": "TC-P1", "parameters": {"port_code": port_code}})


def _q1_vs_others(db, **k):
    # PORT-GEN the clear outlier; next-highest 1.54 (rows ordered DESC by Q1 delay)
    return SQLToolResult("EVD-P2", "SQL-P2", [
        {"port_code": "PORT-GEN", "n_q1": 249, "q1_avg_delay_days": 4.04},
        {"port_code": "PORT-ATL", "n_q1": 113, "q1_avg_delay_days": 1.54},
        {"port_code": "PORT-MED", "n_q1": 176, "q1_avg_delay_days": 1.28},
    ], {"tool_call_id": "TC-P2", "parameters": {}})


def test_rc01_supported_comparative(monkeypatch):
    monkeypatch.setattr(rc01, "port_delay_by_quarter", _by_quarter)
    monkeypatch.setattr(rc01, "port_q1_vs_others", _q1_vs_others)
    resp = rc01.investigate_rc01("fake://db", "PORT-GEN")
    assert resp.outcome == Outcome.SUPPORTED
    assert resp.verification.status == "PASSED"
    assert resp.claims[0].claim_type == ClaimType.COMPARATIVE
    # the derived gap (4.04 - 1.81 = 2.23) must appear in the claim
    assert "2.23" in resp.claims[0].text
    # the control reasoning (outlier / rules out seasonal-everywhere) is in the answer
    assert "worst-performing port" in resp.claims[0].text or "worst" in resp.answer
    assert [t.tool for t in resp.tool_trace] == ["query_database", "query_database", "verify_evidence"]


def test_rc01_no_quarter_data_yields_insufficient(monkeypatch):
    monkeypatch.setattr(rc01, "port_delay_by_quarter",
        lambda db, port_code, **k: SQLToolResult("EVD-P1", "SQL-P1", [], {"tool_call_id": "TC-P1", "parameters": {}}))
    monkeypatch.setattr(rc01, "port_q1_vs_others", _q1_vs_others)
    resp = rc01.investigate_rc01("fake://db", "PORT-GEN")
    assert resp.outcome == Outcome.INSUFFICIENT_EVIDENCE


def test_router_routes_port_questions():
    # LLM forced to a wrong/oos answer so we prove the DETERMINISTIC layer routes correctly
    dummy = lambda s, u: '{"type":"out_of_scope"}'
    # a port-DELAY question (no customers) -> port (RC-01)
    assert router.classify(dummy, "Why are shipments through PORT-GEN delayed in Q1?") == "port"
    # a port-CUSTOMER-impact question -> impact (RC-05), NOT port — pins the ordering invariant
    assert router.classify(dummy, "Which customers are affected by port congestion?") == "impact"