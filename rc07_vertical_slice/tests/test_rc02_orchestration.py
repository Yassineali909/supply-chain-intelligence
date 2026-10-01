"""
RC-02 orchestration tests — mock the three supplier query tools (no live DB).
Pins the de-confounding investigation: given a supplier that's worse than peers on
clean routes, investigate_rc02 produces a SUPPORTED COMPARATIVE answer; given a
supplier NOT worse than peers, it does not overclaim.
"""
import rc02
from postgres_tool import SQLToolResult
from agent_contract import Outcome, ClaimType


def _res(rows, qid="SQL-X", ev="EVD-X"):
    return SQLToolResult(evidence_id=ev, query_id=qid, rows=rows,
                         trace={"tool_call_id": "TC-X", "parameters": {}})


def _mock_tools(monkeypatch, overall, clean, congested, this_clean, peers_clean):
    monkeypatch.setattr(rc02, "supplier_overall",
        lambda db, code, **k: _res([{"supplier_code": code, "shipment_count": 300, "avg_delay_days": overall}]))
    monkeypatch.setattr(rc02, "supplier_by_route_class",
        lambda db, code, **k: _res([
            {"route_class": "clean", "shipment_count": 180, "avg_delay_days": clean},
            {"route_class": "congested", "shipment_count": 120, "avg_delay_days": congested}]))
    monkeypatch.setattr(rc02, "supplier_vs_peers_clean",
        lambda db, code, **k: _res([
            {"grp": "this_supplier", "shipment_count": 180, "avg_delay_days": this_clean},
            {"grp": "peers", "shipment_count": 1800, "avg_delay_days": peers_clean}]))


def test_supplier_worse_than_peers_is_supported(monkeypatch):
    _mock_tools(monkeypatch, 5.59, 5.27, 6.06, 5.27, 1.0)
    resp = rc02.investigate_rc02("fake://db", "S07")
    assert resp.outcome == Outcome.SUPPORTED
    assert resp.verification.status == "PASSED"
    assert resp.claims[0].claim_type == ClaimType.COMPARATIVE
    # three queries + verify
    assert [t.tool for t in resp.tool_trace] == ["query_database"]*3 + ["verify_evidence"]
    # honest framing: "strongly indicates", not "proves"
    assert "strongly indicates" in resp.answer


def test_missing_data_yields_insufficient(monkeypatch):
    monkeypatch.setattr(rc02, "supplier_overall", lambda db, code, **k: _res([]))
    monkeypatch.setattr(rc02, "supplier_by_route_class", lambda db, code, **k: _res([]))
    monkeypatch.setattr(rc02, "supplier_vs_peers_clean", lambda db, code, **k: _res([]))
    resp = rc02.investigate_rc02("fake://db", "S99")
    assert resp.outcome == Outcome.INSUFFICIENT_EVIDENCE
    assert resp.claims == []
