"""
Graph query tool for RC-05 (multi-hop co-exposure). Reusable, read-only, parameterized.
Wraps verified Cypher traversals over the Neo4j projection and returns rows + a trace in
the same shape as the SQL tools, so the agent treats graph and SQL evidence uniformly.

The RC-05 network (suppliers sharing the disrupted route through the congested port) is
passed in rather than hardcoded, so the tool generalizes to any shared-route question.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "devpass123"

COEXPOSURE_CYPHER = """
MATCH (sup:Supplier)-[:RAISED]->(:PurchaseOrder)-[:FULFILLED_BY]->(sh:Shipment)-[:VIA_ROUTE]->(:Route {code:$route})
WHERE sup.code IN $suppliers
MATCH (sh)-[:DELIVERED_TO]->(c:Customer)
WITH c, count(DISTINCT sup) AS n
WHERE n > 1
RETURN count(c) AS co_exposed_customers, max(n) AS max_network_suppliers
""".strip()

PER_SUPPLIER_CYPHER = """
MATCH (sup:Supplier)-[:RAISED]->(:PurchaseOrder)-[:FULFILLED_BY]->(sh:Shipment)-[:VIA_ROUTE]->(:Route {code:$route})
WHERE sup.code IN $suppliers
MATCH (sh)-[:DELIVERED_TO]->(c:Customer)
RETURN sup.code AS supplier, count(DISTINCT c) AS customers
ORDER BY supplier
""".strip()


@dataclass
class GraphToolResult:
    evidence_id: str
    query_id: str
    rows: list[dict[str, Any]]
    trace: dict[str, Any]


def _run(cypher, params, evidence_id, query_id, tool_call_id,
         uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD):
    driver = GraphDatabase.driver(uri, auth=(user, password))
    started = time.perf_counter()
    try:
        with driver.session() as sess:
            rows = [dict(r) for r in sess.run(cypher, **params)]
    finally:
        driver.close()
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    trace = {
        "tool_call_id": tool_call_id, "tool": "graph_query", "query_id": query_id,
        "cypher": cypher, "parameters": params,
        "result_summary": {"row_count": len(rows),
                           "columns": list(rows[0].keys()) if rows else []},
        "elapsed_ms": elapsed_ms,
    }
    return GraphToolResult(evidence_id=evidence_id, query_id=query_id, rows=rows, trace=trace)


def coexposure(route, suppliers, *, evidence_id="EVD-G1", query_id="GRAPH-1", **conn):
    """Count customers co-exposed through a shared route within a supplier network."""
    return _run(COEXPOSURE_CYPHER, {"route": route, "suppliers": suppliers},
                evidence_id, query_id, "TC-G1", **conn)


def per_supplier_reach(route, suppliers, *, evidence_id="EVD-G2", query_id="GRAPH-2", **conn):
    """Per-supplier distinct-customer counts through the shared route."""
    return _run(PER_SUPPLIER_CYPHER, {"route": route, "suppliers": suppliers},
                evidence_id, query_id, "TC-G2", **conn)
