"""
STAGE 10 — factual document skeletons (deterministic).

For each incident, pull the exact codes/dates/numbers the document must contain from
the structured rows (resolving *_id -> *_code via the reference tables, because the
agent searches and cites CODES, not ids).

Relevance rules (this is what makes the refusal test honest):
  - A SEEDED incident (root_cause_id set) tied to a shipment -> DIRECT causal document.
    Its metadata carries root_cause_id.
  - A BACKGROUND incident (root_cause_id None) -> CONTEXTUAL document. root_cause_id None.
"""
from __future__ import annotations

import datagen.config as config
from datagen.model import DocumentSkeleton


DOC_TYPE_BY_INCIDENT = {
    "port_congestion": "incident_report",
    "customs_hold": "incident_report",
    "carrier_delay": "incident_report",
    "capacity_shortfall": "warehouse_report",
    "delay": "supplier_email",
    "damage": "incident_report",
}

CAUSE_HINT_BY_TYPE = {
    "port_congestion": "port congestion",
    "customs_hold": "a customs hold",
    "carrier_delay": "carrier delay",
    "capacity_shortfall": "warehouse capacity shortfall",
    "delay": "supplier lateness",
    "damage": "goods damage",
}


def _index(rows, key):
    return {getattr(r, key): r for r in rows}


def build_skeletons(dataset: dict, scenarios: list | None = None) -> list[DocumentSkeleton]:
    incidents = dataset["incidents"]
    ship_by_id = _index(dataset["shipments"], "shipment_id")
    sup_by_id = _index(dataset["suppliers"], "supplier_id")
    port_by_id = _index(dataset["ports"], "port_id")
    wh_by_id = _index(dataset["warehouses"], "warehouse_id")
    carrier_by_id = _index(dataset["carriers"], "carrier_id")

    skeletons: list[DocumentSkeleton] = []
    doc_counter = 0

    def new_doc_id():
        nonlocal doc_counter
        doc_counter += 1
        return f"DOC-{doc_counter:06d}"

    for inc in incidents:
        codes, dates, numbers = [inc.incident_code], [inc.occurred_on.isoformat()], []
        ship = ship_by_id.get(inc.shipment_id) if inc.shipment_id else None
        if ship is not None:
            codes.append(ship.shipment_code)
            numbers.append(ship.delay_days)
        if inc.supplier_id and inc.supplier_id in sup_by_id:
            codes.append(sup_by_id[inc.supplier_id].code)
        if inc.port_id and inc.port_id in port_by_id:
            codes.append(port_by_id[inc.port_id].code)
        if inc.warehouse_id and inc.warehouse_id in wh_by_id:
            codes.append(wh_by_id[inc.warehouse_id].code)
        if inc.carrier_id and inc.carrier_id in carrier_by_id:
            codes.append(carrier_by_id[inc.carrier_id].code)

        is_direct = inc.root_cause_id is not None and inc.shipment_id is not None
        relevance = "DIRECT" if is_direct else "CONTEXTUAL"
        doc_type = DOC_TYPE_BY_INCIDENT.get(inc.incident_type, "incident_report")

        metadata = {
            "shipment_code": ship.shipment_code if ship else None,
            "incident_code": inc.incident_code,
            "relevance": relevance,
            "root_cause_id": inc.root_cause_id if is_direct else None,
        }
        skeletons.append(DocumentSkeleton(
            doc_id=new_doc_id(), doc_type=doc_type,
            required_codes=[c for c in codes if c],
            required_dates=dates, required_numbers=[n for n in numbers if n is not None],
            cause_hint=CAUSE_HINT_BY_TYPE.get(inc.incident_type, "an operational incident"),
            metadata=metadata,
        ))

    return skeletons
