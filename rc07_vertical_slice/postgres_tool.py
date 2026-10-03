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


# ─────────────────────────── RC-02 supplier-investigation queries ───────────────
# Reusable, parameterized, read-only. The planner chooses which to call; it never
# writes SQL. "clean" route = does not pass through the congested port (PORT-GEN).

CONGESTED_PORT_CODE = "PORT-GEN"

SUPPLIER_OVERALL_SQL = """
SELECT
    sup.code AS supplier_code,
    COUNT(*) AS shipment_count,
    ROUND(AVG(s.delay_days), 2) AS avg_delay_days
FROM shipments AS s
JOIN purchase_orders AS po ON po.po_id = s.po_id
JOIN suppliers AS sup ON sup.supplier_id = po.supplier_id
WHERE sup.code = :supplier_code
GROUP BY sup.code
""".strip()

SUPPLIER_BY_ROUTE_CLASS_SQL = """
SELECT
    CASE WHEN p.code = :congested_port THEN 'congested' ELSE 'clean' END AS route_class,
    COUNT(*) AS shipment_count,
    ROUND(AVG(s.delay_days), 2) AS avg_delay_days
FROM shipments AS s
JOIN purchase_orders AS po ON po.po_id = s.po_id
JOIN suppliers AS sup ON sup.supplier_id = po.supplier_id
JOIN routes AS r ON r.route_id = s.route_id
JOIN ports AS p ON p.port_id = r.port_id
WHERE sup.code = :supplier_code
GROUP BY route_class
""".strip()

SUPPLIER_VS_PEERS_CLEAN_SQL = """
SELECT
    CASE WHEN sup.code = :supplier_code THEN 'this_supplier' ELSE 'peers' END AS grp,
    COUNT(*) AS shipment_count,
    ROUND(AVG(s.delay_days), 2) AS avg_delay_days
FROM shipments AS s
JOIN purchase_orders AS po ON po.po_id = s.po_id
JOIN suppliers AS sup ON sup.supplier_id = po.supplier_id
JOIN routes AS r ON r.route_id = s.route_id
JOIN ports AS p ON p.port_id = r.port_id
WHERE p.code <> :congested_port
GROUP BY grp
""".strip()


def _run(database_url, sql, params, evidence_id, query_id, tool_call_id):
    engine = create_engine(database_url, pool_pre_ping=True)
    started = time.perf_counter()
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql), params)
            rows = [dict(row._mapping) for row in result]
    finally:
        engine.dispose()
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    trace = {
        "tool_call_id": tool_call_id,
        "tool": "query_database",
        "query_id": query_id,
        "sql": sql,
        "parameters": params,
        "result_summary": {"row_count": len(rows),
                           "columns": list(rows[0].keys()) if rows else []},
        "elapsed_ms": elapsed_ms,
    }
    return SQLToolResult(evidence_id=evidence_id, query_id=query_id, rows=rows, trace=trace)


def _validate_supplier_code(code: str):
    if not code or not code.startswith("S") or not code[1:].isdigit():
        raise ValueError("supplier_code must look like S07")


def supplier_overall(database_url, supplier_code, *, evidence_id="EVD-A", query_id="SQL-A"):
    """Overall shipment count + avg delay for one supplier."""
    _validate_supplier_code(supplier_code)
    return _run(database_url, SUPPLIER_OVERALL_SQL,
                {"supplier_code": supplier_code},
                evidence_id, query_id, "TC-A")


def supplier_by_route_class(database_url, supplier_code, *, evidence_id="EVD-B", query_id="SQL-B"):
    """Avg delay split into clean vs congested routes for one supplier (de-confounding)."""
    _validate_supplier_code(supplier_code)
    return _run(database_url, SUPPLIER_BY_ROUTE_CLASS_SQL,
                {"supplier_code": supplier_code, "congested_port": CONGESTED_PORT_CODE},
                evidence_id, query_id, "TC-B")


def supplier_vs_peers_clean(database_url, supplier_code, *, evidence_id="EVD-C", query_id="SQL-C"):
    """Supplier vs all other suppliers, on CLEAN routes only (apples-to-apples)."""
    _validate_supplier_code(supplier_code)
    return _run(database_url, SUPPLIER_VS_PEERS_CLEAN_SQL,
                {"supplier_code": supplier_code, "congested_port": CONGESTED_PORT_CODE},
                evidence_id, query_id, "TC-C")


# ─────────────────────────── RC-04 warehouse stage-localization queries ─────────
# The trap: during the demand peak, a capacity-limited warehouse slips on OUTBOUND
# deliveries while INBOUND shipments arrive normally. A naive agent blames the supplier;
# the correct answer localizes the delay to the warehouse's outbound stage.

WH_INBOUND_OUTBOUND_SQL = """
SELECT
    CASE WHEN EXTRACT(MONTH FROM d.planned_date) IN (6,7) THEN 'peak' ELSE 'non_peak' END AS period,
    COUNT(*) AS n,
    ROUND(AVG(sh.delay_days), 2) AS inbound_delay_days,
    ROUND(AVG(d.delay_days), 2) AS outbound_delay_days
FROM deliveries AS d
JOIN shipments AS sh ON sh.shipment_id = d.shipment_id
JOIN warehouses AS w ON w.warehouse_id = d.warehouse_id
WHERE w.code = :warehouse_code
GROUP BY period
ORDER BY period
""".strip()

WH_VS_OTHERS_PEAK_SQL = """
SELECT
    w.code AS warehouse_code,
    ROUND(AVG(sh.delay_days), 2) AS inbound_delay_days,
    ROUND(AVG(d.delay_days), 2) AS outbound_delay_days
FROM deliveries AS d
JOIN shipments AS sh ON sh.shipment_id = d.shipment_id
JOIN warehouses AS w ON w.warehouse_id = d.warehouse_id
WHERE EXTRACT(MONTH FROM d.planned_date) IN (6,7)
GROUP BY w.code
ORDER BY outbound_delay_days DESC
""".strip()


def _validate_warehouse_code(code: str):
    if not code or not code.startswith("WH-"):
        raise ValueError("warehouse_code must look like WH-2")


def warehouse_inbound_vs_outbound(database_url, warehouse_code, *, evidence_id="EVD-W1", query_id="SQL-W1"):
    """Inbound (shipment) vs outbound (delivery) delay for one warehouse, peak vs non-peak."""
    _validate_warehouse_code(warehouse_code)
    return _run(database_url, WH_INBOUND_OUTBOUND_SQL,
                {"warehouse_code": warehouse_code},
                evidence_id, query_id, "TC-W1")


def warehouse_vs_others_peak(database_url, *, evidence_id="EVD-W2", query_id="SQL-W2"):
    """All warehouses' inbound vs outbound delay during the peak (is one uniquely bad outbound?)."""
    return _run(database_url, WH_VS_OTHERS_PEAK_SQL, {},
                evidence_id, query_id, "TC-W2")


# ─────────────────────────── RC-01 port-congestion queries ──────────────────────
# RC-01's signal is TEMPORAL: a port's delay spikes in Q1 vs the rest of the year.
# Like RC-04, the second tool is a cross-entity control — it rules out "Q1 is just
# slow everywhere" by showing the port is the clear outlier among all ports in Q1.
# NOTE: quarter is bucketed on planned_departure (the live Q1 figure is ~4.04 on
# this bucketing; the handoff's ~5.06 was a different slice — do not chase it).
# Numbers are returned from SQL at runtime, never hardcoded, so the COMPARATIVE
# claim's base figures always match the evidence the verifier checks.

PORT_DELAY_BY_QUARTER_SQL = """
SELECT
    CASE WHEN EXTRACT(QUARTER FROM s.planned_departure) = 1 THEN 'Q1' ELSE 'rest' END AS period,
    COUNT(*) AS n,
    ROUND(AVG(s.delay_days), 2) AS avg_delay_days
FROM shipments AS s
JOIN routes AS r ON r.route_id = s.route_id
JOIN ports AS p ON p.port_id = r.port_id
WHERE p.code = :port_code
GROUP BY period
ORDER BY period
""".strip()

PORT_Q1_VS_OTHERS_SQL = """
SELECT
    p.code AS port_code,
    COUNT(*) AS n_q1,
    ROUND(AVG(s.delay_days), 2) AS q1_avg_delay_days
FROM shipments AS s
JOIN routes AS r ON r.route_id = s.route_id
JOIN ports AS p ON p.port_id = r.port_id
WHERE EXTRACT(QUARTER FROM s.planned_departure) = 1
GROUP BY p.code
ORDER BY q1_avg_delay_days DESC
""".strip()


def _validate_port_code(code: str):
    if not code or not code.startswith("PORT-"):
        raise ValueError("port_code must look like PORT-GEN")


def port_delay_by_quarter(database_url, port_code, *, evidence_id="EVD-P1", query_id="SQL-P1"):
    """One port's avg delay, Q1 vs the rest of the year (the core RC-01 signal)."""
    _validate_port_code(port_code)
    return _run(database_url, PORT_DELAY_BY_QUARTER_SQL,
                {"port_code": port_code},
                evidence_id, query_id, "TC-P1")


def port_q1_vs_others(database_url, *, evidence_id="EVD-P2", query_id="SQL-P2"):
    """All ports' Q1 avg delay (is this port the clear outlier, or is Q1 slow everywhere?)."""
    return _run(database_url, PORT_Q1_VS_OTHERS_SQL, {},
                evidence_id, query_id, "TC-P2")


# ─────────────────────────── RC-03 carrier-degradation queries ──────────────────
# RC-03's signal is a TREND: a carrier's delay climbs GRADUALLY over the 24 months.
# Unlike RC-01's clean two-bucket gap, this is a noisy monotonic-ish rise — which is
# exactly why the honest verdict is PARTIALLY_SUPPORTED (a measurable degradation, but
# no single pinpointable cause). Claim is built from THIRDS (early/mid/late), never from
# single-month endpoints — one sparse month (e.g. a lone late shipment) must not drive it.
# Second tool is the fleet control: it rules out "the whole fleet is slowing," so the
# trend is attributable to THIS carrier. Numbers derived from SQL at runtime, not hardcoded.

CARRIER_THIRDS_SQL = """
WITH bounds AS (
    SELECT MIN(planned_departure) AS d0, MAX(planned_departure) AS d1 FROM shipments
)
SELECT
    width_bucket(
        EXTRACT(EPOCH FROM s.planned_departure),
        EXTRACT(EPOCH FROM b.d0),
        EXTRACT(EPOCH FROM b.d1) + 1,
        3
    ) AS third,
    COUNT(*) AS n,
    ROUND(AVG(s.delay_days), 2) AS avg_delay_days
FROM shipments AS s
JOIN carriers AS c ON c.carrier_id = s.carrier_id
CROSS JOIN bounds b
WHERE c.code = :carrier_code
GROUP BY third
ORDER BY third
""".strip()

CARRIER_THIRDS_FLEET_SQL = """
WITH bounds AS (
    SELECT MIN(planned_departure) AS d0, MAX(planned_departure) AS d1 FROM shipments
)
SELECT
    width_bucket(
        EXTRACT(EPOCH FROM s.planned_departure),
        EXTRACT(EPOCH FROM b.d0),
        EXTRACT(EPOCH FROM b.d1) + 1,
        3
    ) AS third,
    COUNT(*) AS n,
    ROUND(AVG(s.delay_days), 2) AS avg_delay_days
FROM shipments AS s
JOIN carriers AS c ON c.carrier_id = s.carrier_id
CROSS JOIN bounds b
WHERE c.code <> :carrier_code
GROUP BY third
ORDER BY third
""".strip()


def _validate_carrier_code(code: str):
    if not code or not code.startswith("CR") or not code[2:].isdigit():
        raise ValueError("carrier_code must look like CR3")


def carrier_delay_by_thirds(database_url, carrier_code, *, evidence_id="EVD-T1", query_id="SQL-T1"):
    """One carrier's avg delay across early/mid/late thirds of the 24-month window (the trend)."""
    _validate_carrier_code(carrier_code)
    return _run(database_url, CARRIER_THIRDS_SQL,
                {"carrier_code": carrier_code},
                evidence_id, query_id, "TC-T1")


def carrier_thirds_fleet(database_url, carrier_code, *, evidence_id="EVD-T2", query_id="SQL-T2"):
    """All OTHER carriers' avg delay by third (is the trend carrier-specific or fleet-wide?)."""
    _validate_carrier_code(carrier_code)
    return _run(database_url, CARRIER_THIRDS_FLEET_SQL,
                {"carrier_code": carrier_code},
                evidence_id, query_id, "TC-T2")