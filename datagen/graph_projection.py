"""
STAGE 9 — build the Neo4j projection FROM PostgreSQL rows only.

The graph is a PROJECTION of the in-memory dataset (the Postgres source of truth), so
this writer is IDEMPOTENT: it clears the graph and rebuilds every run. No graph-only
business fact exists; everything is reconstructable from the base tables.

Delivery is a REAL node; the direct (Shipment)-[:DELIVERED_TO]->(Customer) edge is a
DERIVED SHORTCUT over Shipment->Delivery->Customer, kept for fast traversal but never an
independent fact. The graph inherits the hidden-lever strip from the dataset.
"""
from __future__ import annotations

from neo4j import GraphDatabase

import datagen.config as config


def _clear(tx):
    tx.run("MATCH (n) DETACH DELETE n")


def _constraints(tx):
    for label, key in [("Supplier", "code"), ("Customer", "code"), ("Shipment", "code"),
                       ("Route", "code"), ("Port", "code"), ("Warehouse", "code"),
                       ("Carrier", "code"), ("PurchaseOrder", "code"),
                       ("Incident", "code"), ("Delivery", "code")]:
        tx.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.{key} IS UNIQUE")


def _load_nodes(tx, dataset):
    tx.run("UNWIND $rows AS r CREATE (:Supplier {code:r.code, name:r.name, country:r.country})",
           rows=[{"code": s.code, "name": s.name, "country": s.country} for s in dataset["suppliers"]])
    tx.run("UNWIND $rows AS r CREATE (:Customer {code:r.code, name:r.name, priority:r.priority})",
           rows=[{"code": c.code, "name": c.name, "priority": c.priority_tier} for c in dataset["customers"]])
    tx.run("UNWIND $rows AS r CREATE (:Port {code:r.code, name:r.name})",
           rows=[{"code": p.code, "name": p.name} for p in dataset["ports"]])
    tx.run("UNWIND $rows AS r CREATE (:Warehouse {code:r.code, name:r.name})",
           rows=[{"code": w.code, "name": w.name} for w in dataset["warehouses"]])
    tx.run("UNWIND $rows AS r CREATE (:Carrier {code:r.code, name:r.name, mode:r.mode})",
           rows=[{"code": c.code, "name": c.name, "mode": c.mode} for c in dataset["carriers"]])
    tx.run("UNWIND $rows AS r CREATE (:Route {code:r.code, name:r.name})",
           rows=[{"code": r.code, "name": r.name} for r in dataset["routes"]])
    tx.run("UNWIND $rows AS r CREATE (:Shipment {code:r.code, delay_days:r.delay, status:r.status})",
           rows=[{"code": s.shipment_code, "delay": s.delay_days, "status": s.status} for s in dataset["shipments"]])
    tx.run("UNWIND $rows AS r CREATE (:PurchaseOrder {code:r.code})",
           rows=[{"code": po.po_code} for po in dataset["purchase_orders"]])
    tx.run("UNWIND $rows AS r CREATE (:Delivery {code:r.code, delay_days:r.delay})",
           rows=[{"code": d.delivery_code, "delay": d.delay_days} for d in dataset["deliveries"]])
    tx.run("UNWIND $rows AS r CREATE (:Incident {code:r.code, type:r.type, severity:r.sev})",
           rows=[{"code": i.incident_code, "type": i.incident_type, "sev": i.severity} for i in dataset["incidents"]])


def _load_rels(tx, dataset):
    sup = {s.supplier_id: s.code for s in dataset["suppliers"]}
    cust = {c.customer_id: c.code for c in dataset["customers"]}
    port = {p.port_id: p.code for p in dataset["ports"]}
    wh = {w.warehouse_id: w.code for w in dataset["warehouses"]}
    carr = {c.carrier_id: c.code for c in dataset["carriers"]}
    route = {r.route_id: r.code for r in dataset["routes"]}
    po_sup = {po.po_id: sup[po.supplier_id] for po in dataset["purchase_orders"]}
    po_code = {po.po_id: po.po_code for po in dataset["purchase_orders"]}
    ship_code = {s.shipment_id: s.shipment_code for s in dataset["shipments"]}

    tx.run("UNWIND $rows AS r MATCH (rt:Route {code:r.rc}),(p:Port {code:r.pc}) CREATE (rt)-[:THROUGH_PORT]->(p)",
           rows=[{"rc": rt.code, "pc": port[rt.port_id]} for rt in dataset["routes"]])
    tx.run("UNWIND $rows AS r MATCH (rt:Route {code:r.rc}),(w:Warehouse {code:r.wc}) CREATE (rt)-[:ENDS_AT]->(w)",
           rows=[{"rc": rt.code, "wc": wh[rt.warehouse_id]} for rt in dataset["routes"]])
    tx.run("UNWIND $rows AS r MATCH (s:Supplier {code:r.sc}),(po:PurchaseOrder {code:r.pc}) CREATE (s)-[:RAISED]->(po)",
           rows=[{"sc": po_sup[po.po_id], "pc": po.po_code} for po in dataset["purchase_orders"]])
    tx.run("UNWIND $rows AS r MATCH (po:PurchaseOrder {code:r.pc}),(sh:Shipment {code:r.sc}) CREATE (po)-[:FULFILLED_BY]->(sh)",
           rows=[{"pc": po_code[s.po_id], "sc": s.shipment_code} for s in dataset["shipments"]])
    tx.run("UNWIND $rows AS r MATCH (sh:Shipment {code:r.sc}),(rt:Route {code:r.rc}) CREATE (sh)-[:VIA_ROUTE]->(rt)",
           rows=[{"sc": s.shipment_code, "rc": route[s.route_id]} for s in dataset["shipments"]])
    tx.run("UNWIND $rows AS r MATCH (sh:Shipment {code:r.sc}),(c:Carrier {code:r.cc}) CREATE (sh)-[:CARRIED_BY]->(c)",
           rows=[{"sc": s.shipment_code, "cc": carr[s.carrier_id]} for s in dataset["shipments"]])
    tx.run("UNWIND $rows AS r MATCH (sh:Shipment {code:r.sc}),(d:Delivery {code:r.dc}) CREATE (sh)-[:HAS_DELIVERY]->(d)",
           rows=[{"sc": ship_code[d.shipment_id], "dc": d.delivery_code} for d in dataset["deliveries"]])
    tx.run("UNWIND $rows AS r MATCH (d:Delivery {code:r.dc}),(c:Customer {code:r.cc}) CREATE (d)-[:TO_CUSTOMER]->(c)",
           rows=[{"dc": d.delivery_code, "cc": cust[d.customer_id]} for d in dataset["deliveries"]])
    tx.run("UNWIND $rows AS r MATCH (sh:Shipment {code:r.sc}),(c:Customer {code:r.cc}) CREATE (sh)-[:DELIVERED_TO]->(c)",
           rows=[{"sc": ship_code[d.shipment_id], "cc": cust[d.customer_id]} for d in dataset["deliveries"]])
    tx.run("UNWIND $rows AS r MATCH (i:Incident {code:r.ic}),(sh:Shipment {code:r.sc}) CREATE (i)-[:AFFECTS]->(sh)",
           rows=[{"ic": i.incident_code, "sc": ship_code[i.shipment_id]}
                 for i in dataset["incidents"] if i.shipment_id in ship_code])


def project_graph(dataset: dict, uri=None, user=None, password=None) -> dict:
    uri = uri or config.NEO4J_URI
    user = user or config.NEO4J_USER
    password = password or config.NEO4J_PASSWORD
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as sess:
            sess.execute_write(_clear)
            sess.execute_write(_constraints)
            sess.execute_write(_load_nodes, dataset)
            sess.execute_write(_load_rels, dataset)
            counts = sess.run("MATCH (n) RETURN count(n) AS nodes").single()["nodes"]
            rels = sess.run("MATCH ()-[r]->() RETURN count(r) AS rels").single()["rels"]
    finally:
        driver.close()
    print(f"[graph] projected {counts} nodes, {rels} relationships to {uri}")
    return {"nodes": counts, "relationships": rels}
