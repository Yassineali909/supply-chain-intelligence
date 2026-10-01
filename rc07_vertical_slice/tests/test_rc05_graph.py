"""
RC-05 graph investigation tests. Mock the graph tools (no live Neo4j needed) so the
assembly + routing logic is pinned deterministically.
"""
import rc05
import router
from graph_tool import GraphToolResult
from agent_contract import Outcome, ClaimType


def _coexp(route, suppliers, **k):
    return GraphToolResult("EVD-G1", "GRAPH-1",
        [{"co_exposed_customers": 21, "max_network_suppliers": 2}],
        {"tool_call_id": "TC-G1", "parameters": {}})


def _per(route, suppliers, **k):
    return GraphToolResult("EVD-G2", "GRAPH-2",
        [{"supplier": s, "customers": 14 + i} for i, s in enumerate(suppliers)],
        {"tool_call_id": "TC-G2", "parameters": {}})


def test_rc05_produces_relationship_claim(monkeypatch):
    monkeypatch.setattr(rc05, "coexposure", _coexp)
    monkeypatch.setattr(rc05, "per_supplier_reach", _per)
    resp = rc05.investigate_rc05()
    assert resp.outcome == Outcome.SUPPORTED
    assert resp.verification.status == "PASSED"
    assert resp.claims[0].claim_type == ClaimType.RELATIONSHIP
    assert "21" in resp.answer
    assert [t.tool for t in resp.tool_trace] == ["graph_query", "graph_query", "verify_evidence"]


def test_rc05_empty_graph_yields_insufficient(monkeypatch):
    monkeypatch.setattr(rc05, "coexposure",
        lambda r, s, **k: GraphToolResult("EVD-G1", "GRAPH-1", [], {"tool_call_id": "TC-G1"}))
    monkeypatch.setattr(rc05, "per_supplier_reach", _per)
    resp = rc05.investigate_rc05()
    assert resp.outcome == Outcome.INSUFFICIENT_EVIDENCE


def test_router_routes_impact_questions():
    good = lambda s, u: '{"type":"impact"}'
    assert router.classify(good, "Which customers are affected by port congestion?") == "impact"
    # deterministic fallback also catches it
    garbage = lambda s, u: "no json"
    assert router.classify(garbage, "Which customers are affected by the congestion cascade?") == "impact"
