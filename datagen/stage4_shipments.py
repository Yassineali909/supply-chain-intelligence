"""
STAGE 4 — shipments. THE CAUSAL HEART.

For each PO: create a shipment on the PO's intended route (from stage 3), assign a
carrier + mode, compute planned dates from route transit, then compute ACTUAL dates by
applying the shipment-stage levers (levers.total_shipment_delay). Per-lever attribution
is recorded on each shipment (_delay_attribution) for the evidence floor.

Do NOT apply the warehouse lever here — that is a DELIVERY-stage effect (RC-04, stage 5).
RC-06 target shipments are picked here: delayed, but flagged so stage 7 gives them NO
seeded incident and stage 10 gives them NO direct document.
"""
from __future__ import annotations

from datetime import timedelta

import datagen.config as config
from datagen.seed import child_stream
from datagen.model import Shipment
from datagen.levers import total_shipment_delay
from datagen.stage3_orders import _window_days


def build_shipments(root, reference: dict, orders: dict) -> dict:
    rng = child_stream(root, "shipments")
    start, end = _window_days()
    window_days = (end - start).days

    routes_by_code = {r.code: r for r in reference["routes"]}
    ports_by_id = {p.port_id: p for p in reference["ports"]}
    suppliers_by_id = {s.supplier_id: s for s in reference["suppliers"]}
    carriers = reference["carriers"]

    shipments = []
    ship_counter = 4000

    for po in orders["purchase_orders"]:
        route = routes_by_code[po._intended_route_code]
        port = ports_by_id[route.port_id]
        supplier = suppliers_by_id[po.supplier_id]
        carrier = carriers[int(rng.integers(0, len(carriers)))]

        planned_departure = po.order_date + timedelta(days=int(rng.integers(1, 5)))
        planned_arrival = planned_departure + timedelta(days=route.planned_transit_days)

        delay, attribution = total_shipment_delay(
            rng, supplier, route, port, carrier,
            planned_arrival, start, window_days,
        )

        actual_arrival = planned_arrival + timedelta(days=delay)
        status = "delayed" if delay > 0 else "arrived"

        ship_counter += 1
        sh = Shipment(
            shipment_id=ship_counter,
            shipment_code=f"SH-{ship_counter}",
            po_id=po.po_id,
            route_id=route.route_id,
            carrier_id=carrier.carrier_id,
            mode=carrier.mode,
            planned_departure=planned_departure,
            planned_arrival=planned_arrival,
            actual_departure=planned_departure,
            actual_arrival=actual_arrival,
            delay_days=delay,
            status=status,
        )
        sh._delay_attribution = attribution
        sh._is_peak = getattr(po, "_peak", False)
        sh._rc06_target = False
        shipments.append(sh)

    candidates = [
        s for s in shipments
        if s.delay_days >= 3
        and s._delay_attribution["supplier"] == 0
        and s._delay_attribution["port"] == 0
        and s._delay_attribution["carrier"] == 0
    ]
    n_rc06 = min(5, len(candidates))
    for idx in rng.choice(len(candidates), size=n_rc06, replace=False):
        candidates[int(idx)]._rc06_target = True

    return {"shipments": shipments}
