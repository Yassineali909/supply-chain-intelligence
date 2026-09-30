"""
Orchestration tests for investigate_rc07 — the code path the fixture tests bypass.

These monkeypatch the SQL tool (so no live database is needed) and use a temp document
directory, exercising the THREE real outcome paths of the orchestration:

  1. shipment found + DIRECT document        -> SUPPORTED
  2. shipment found + NO direct document      -> INSUFFICIENT_EVIDENCE (the refusal path)
  3. shipment not found                       -> INSUFFICIENT_EVIDENCE (missing entity)

Path 2 is the honest-refusal behaviour (the RC-06 mechanism inside RC-07's code) and
is the most important one to pin — nothing proved it worked before this test.
"""
import json
from pathlib import Path

import pytest

import rc07
from postgres_tool import SQLToolResult
from agent_contract import Outcome


def _fake_sql_result(shipment_code="SH-4921", delay_days=8, found=True):
    if not found:
        rows = []
    else:
        rows = [{
            "shipment_code": shipment_code,
            "planned_arrival": "2026-02-06",
            "actual_arrival": "2026-02-14",
            "delay_days": delay_days,
            "status": "delayed",
            "route_code": "RT-08",
            "port_code": "PORT-ADR",
            "port_name": "Rotterdam",
            "warehouse_code": "WH-1",
            "carrier_code": "CR2",
        }]
    return SQLToolResult(
        evidence_id="EVD-001",
        query_id="SQL-0001",
        rows=rows,
        trace={"tool_call_id": "TC-001", "tool": "query_database", "query_id": "SQL-0001",
               "sql": "SELECT ...", "parameters": {"shipment_code": shipment_code},
               "result_summary": {"row_count": len(rows), "columns": list(rows[0].keys()) if rows else []},
               "elapsed_ms": 1},
    )


def _write_doc(tmp_path: Path, relevance: str, shipment_code="SH-4921"):
    doc = {
        "doc_id": "DOC-TEST-RC07",
        "doc_type": "incident_report",
        "text": f"Incident INC-042: Shipment {shipment_code} was held at PORT-ADR for customs clearance.",
        "metadata": {
            "shipment_code": shipment_code,
            "incident_code": "INC-042",
            "port_code": "PORT-ADR",
            "relevance": relevance,
        },
    }
    (tmp_path / "doc.json").write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path


def test_path1_direct_document_yields_supported(tmp_path, monkeypatch):
    monkeypatch.setattr(rc07, "query_shipment", lambda url, code, **kw: _fake_sql_result(code))
    root = _write_doc(tmp_path, relevance="DIRECT")
    resp = rc07.investigate_rc07("fake://db", str(root), "SH-4921")
    assert resp.outcome == Outcome.SUPPORTED
    assert resp.verification.status == "PASSED"
    assert any(c.claim_type.value == "NUMERIC" for c in resp.claims)
    assert any(c.claim_type.value == "CAUSAL" for c in resp.claims)
    assert all(c.evidence_ids for c in resp.claims)


def test_path2_no_direct_document_yields_insufficient(tmp_path, monkeypatch):
    """The refusal path: shipment exists, but only a CONTEXTUAL doc -> no invented cause."""
    monkeypatch.setattr(rc07, "query_shipment", lambda url, code, **kw: _fake_sql_result(code))
    root = _write_doc(tmp_path, relevance="CONTEXTUAL")
    resp = rc07.investigate_rc07("fake://db", str(root), "SH-4921")
    assert resp.outcome == Outcome.INSUFFICIENT_EVIDENCE
    assert not any(c.claim_type.value == "CAUSAL" for c in resp.claims)
    assert any(c.claim_type.value == "NUMERIC" for c in resp.claims)


def test_path3_shipment_not_found_yields_insufficient(tmp_path, monkeypatch):
    monkeypatch.setattr(rc07, "query_shipment", lambda url, code, **kw: _fake_sql_result(code, found=False))
    root = _write_doc(tmp_path, relevance="DIRECT")
    resp = rc07.investigate_rc07("fake://db", str(root), "SH-9999")
    assert resp.outcome == Outcome.INSUFFICIENT_EVIDENCE
    assert resp.claims == []
    assert resp.evidence == []
