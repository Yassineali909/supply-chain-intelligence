"""
STAGE 9 — build the Neo4j projection FROM PostgreSQL rows only.

Nodes: Supplier, PurchaseOrder, Shipment, Route, Port, Warehouse, Delivery, Customer,
Carrier, Incident. Delivery is a REAL node; the direct (Shipment)-[:DELIVERED_TO]->
(Customer) edge is a DERIVED SHORTCUT over Shipment->Delivery->Customer and must be
reconstructable/removable from Postgres alone. No graph-only business fact may exist.
"""
from __future__ import annotations
import datagen.config as config


def project_graph(dataset: dict) -> dict:
    """Return {'nodes': [...], 'relationships': [...]} derived purely from Postgres."""
    raise NotImplementedError
