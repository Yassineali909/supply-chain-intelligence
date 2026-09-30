from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, text


RC07_SHIPMENT_SQL = """
SELECT
    s.shipment_code,
    s.planned_arrival,
    s.actual_arrival,
    s.delay_days,
    s.status,
    r.code AS route_code,
    p.code AS port_code,
    p.name AS port_name,
    w.code AS warehouse_code,
    c.code AS carrier_code
FROM shipments AS s
JOIN routes AS r ON r.route_id = s.route_id
JOIN ports AS p ON p.port_id = r.port_id
JOIN warehouses AS w ON w.warehouse_id = r.warehouse_id
JOIN carriers AS c ON c.carrier_id = s.carrier_id
WHERE s.shipment_code = :shipment_code
""".strip()


@dataclass
class SQLToolResult:
    evidence_id: str
    query_id: str
    rows: list[dict[str, Any]]
    trace: dict[str, Any]


def query_shipment(database_url: str, shipment_code: str, *, evidence_id: str = "EVD-001", query_id: str = "SQL-0001") -> SQLToolResult:
    if not shipment_code or not shipment_code.startswith("SH-"):
        raise ValueError("shipment_code must look like SH-4921")

    engine = create_engine(database_url, pool_pre_ping=True)
    started = time.perf_counter()
    try:
        with engine.connect() as conn:
            result = conn.execute(text(RC07_SHIPMENT_SQL), {"shipment_code": shipment_code})
            rows = [dict(row._mapping) for row in result]
    finally:
        engine.dispose()
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    trace = {
        "tool_call_id": "TC-001",
        "tool": "query_database",
        "query_id": query_id,
        "sql": RC07_SHIPMENT_SQL,
        "parameters": {"shipment_code": shipment_code},
        "result_summary": {
            "row_count": len(rows),
            "columns": list(rows[0].keys()) if rows else [],
        },
        "elapsed_ms": elapsed_ms,
    }
    return SQLToolResult(evidence_id=evidence_id, query_id=query_id, rows=rows, trace=trace)
