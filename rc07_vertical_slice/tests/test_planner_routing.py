"""
Planner routing tests — with MOCK routers, so no live LLM/database is needed.

These pin the agent's control-loop robustness. The 'stubborn' case is the real failure
llama3.2:3b exhibited (looping query_database); the state-constrained action space must
prevent it. If a future change lets the loop back in, this test goes red.
"""
import json
import tempfile
from pathlib import Path

import planner
from postgres_tool import SQLToolResult
from agent_contract import Outcome


def _fake_sql(url, code, **kw):
    rows = [{
        "shipment_code": code, "planned_arrival": "2026-02-06",
        "actual_arrival": "2026-02-14", "delay_days": 8, "status": "delayed",
        "route_code": "RT-08", "port_code": "PORT-ADR", "port_name": "Rotterdam",
        "warehouse_code": "WH-1", "carrier_code": "CR2",
    }]
    return SQLToolResult(evidence_id="EVD-001", query_id="SQL-0001", rows=rows,
                         trace={"tool_call_id": "TC-001"})


def _doc_root(tmp_path, relevance="DIRECT"):
    (tmp_path / "doc.json").write_text(json.dumps({
        "doc_id": "DOC-1", "doc_type": "incident_report",
        "text": "Incident INC-042: SH-4921 held at PORT-ADR for customs, 8 days of delay.",
        "metadata": {"shipment_code": "SH-4921", "incident_code": "INC-042", "relevance": relevance},
    }), encoding="utf-8")
    return str(tmp_path)


def _good(system, user):
    if 'have_shipment": false' in user:
        return '{"action":"query_database"}'
    if 'have_documents": false' in user:
        return '{"action":"search_documents"}'
    return '{"action":"finish"}'


def _stubborn(system, user):
    # The real llama3.2:3b failure mode: always wants to query the database.
    return '{"action":"query_database","reason":"check again"}'


def _garbage(system, user):
    return "no json here, just rambling about databases"


def test_good_router_produces_clean_trace(tmp_path, monkeypatch):
    monkeypatch.setattr(planner, "query_shipment", _fake_sql)
    resp = planner.investigate_with_planner(_good, "fake://db", _doc_root(tmp_path), "SH-4921")
    assert resp.outcome == Outcome.SUPPORTED
    assert resp.verification.status == "PASSED"
    assert [t.tool for t in resp.tool_trace] == ["query_database", "search_documents", "verify_evidence"]


def test_stubborn_router_cannot_loop(tmp_path, monkeypatch):
    """A router that always says query_database must NOT loop — the action space forbids it."""
    monkeypatch.setattr(planner, "query_shipment", _fake_sql)
    resp = planner.investigate_with_planner(_stubborn, "fake://db", _doc_root(tmp_path), "SH-4921")
    tools = [t.tool for t in resp.tool_trace]
    assert tools.count("query_database") == 1, f"looped: {tools}"
    assert "search_documents" in tools
    assert resp.verification.status == "PASSED"


def test_garbage_router_falls_back_safely(tmp_path, monkeypatch):
    monkeypatch.setattr(planner, "query_shipment", _fake_sql)
    resp = planner.investigate_with_planner(_garbage, "fake://db", _doc_root(tmp_path), "SH-4921")
    assert [t.tool for t in resp.tool_trace] == ["query_database", "search_documents", "verify_evidence"]
    assert resp.verification.status == "PASSED"
