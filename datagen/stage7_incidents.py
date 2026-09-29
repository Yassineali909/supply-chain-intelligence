"""
STAGE 7 — incidents. Generated AFTER the delays they explain (stages 4-5), so an
incident always corresponds to a real delay.

Two kinds:
  * SEEDED incidents carry a root_cause_id and explain a levered delay, decided by
    inspecting each shipment's _delay_attribution (port->RC-01, supplier->RC-02,
    carrier->RC-03), plus delivery warehouse-slip->RC-04 and the single customs hold->RC-07.
  * BACKGROUND incidents carry root_cause_id=None — noise the agent must see past.

RC-06 targets get NO incident from ANY path: that absence IS the refusal test, and it
is asserted. (RC-04 and RC-06 can collide on the same shipment, so RC-06 targets are
excluded from the RC-04 path too, not just background.)
"""
from __future__ import annotations

from datetime import timedelta

import datagen.config as config
from datagen.seed import child_stream
from datagen.model import Incident


def _dominant_cause(attr: dict) -> str:
    """Return the lever name with the largest contribution ('base' if none dominate)."""
    levers = {k: v for k, v in attr.items() if k in ("supplier", "port", "carrier")}
    if not levers or max(levers.values()) <= 0:
        return "base"
    return max(levers, key=levers.get)


def build_incidents(root, reference: dict, orders: dict, shipments: dict,
                    deliveries: dict) -> dict:
    rng = child_stream(root, "incidents")

    po_by_id = {po.po_id: po for po in orders["purchase_orders"]}
    routes_by_id = {r.route_id: r for r in reference["routes"]}
    rc06_ship_ids = {s.shipment_id for s in shipments["shipments"]
                     if getattr(s, "_rc06_target", False)}
    incidents = []
    inc_counter = 0

    def new_incident(itype, severity, when, root_cause_id=None, **links):
        nonlocal inc_counter
        inc_counter += 1
        return Incident(
            incident_id=inc_counter,
            incident_code=f"INC-{inc_counter:03d}",
            incident_type=itype,
            severity=severity,
            occurred_on=when,
            root_cause_id=root_cause_id,
            **links,
        )

    # --- SEEDED incidents from shipment attribution ---
    for sh in shipments["shipments"]:
        if getattr(sh, "_rc06_target", False):
            continue  # RC-06: deliberately no incident
        if sh.delay_days < 3:
            continue
        cause = _dominant_cause(sh._delay_attribution)
        route = routes_by_id[sh.route_id]
        po = po_by_id[sh.po_id]
        if cause == "port":
            incidents.append(new_incident(
                "port_congestion", "high", sh.planned_arrival, root_cause_id="RC-01",
                shipment_id=sh.shipment_id, port_id=route.port_id))
        elif cause == "supplier":
            incidents.append(new_incident(
                "delay", "medium", sh.planned_arrival, root_cause_id="RC-02",
                shipment_id=sh.shipment_id, supplier_id=po.supplier_id))
        elif cause == "carrier":
            incidents.append(new_incident(
                "carrier_delay", "medium", sh.planned_arrival, root_cause_id="RC-03",
                shipment_id=sh.shipment_id, carrier_id=sh.carrier_id))

    # --- SEEDED capacity incidents from deliveries (RC-04) ---
    # Exclude RC-06 target shipments: their delay must remain unexplained, so no
    # incident of ANY kind (including a warehouse-slip incident on their delivery)
    # may reference them. This is the collision between RC-04 and RC-06.
    for dl in deliveries["deliveries"]:
        if dl.shipment_id in rc06_ship_ids:
            continue
        if dl._delay_attribution.get("warehouse", 0) > 0:
            incidents.append(new_incident(
                "capacity_shortfall", "high", dl.planned_date, root_cause_id="RC-04",
                warehouse_id=dl.warehouse_id, shipment_id=dl.shipment_id))

    # --- RC-07: one isolated customs hold on a specific high-value shipment ---
    portadr_pid = [p.port_id for p in reference["ports"] if p.code == "PORT-ADR"][0]
    adr_routes = {r.route_id for r in reference["routes"] if r.port_id == portadr_pid}
    rc07_candidates = [s for s in shipments["shipments"]
                       if s.route_id in adr_routes and not getattr(s, "_rc06_target", False)]
    if rc07_candidates:
        target = rc07_candidates[int(rng.integers(0, len(rc07_candidates)))]
        target.delay_days = max(target.delay_days, 8)
        target.actual_arrival = target.planned_arrival + timedelta(days=target.delay_days)
        target.status = "delayed"
        target._rc07_target = True
        incidents.append(new_incident(
            "customs_hold", "high", target.planned_arrival, root_cause_id="RC-07",
            shipment_id=target.shipment_id, port_id=portadr_pid))

    # --- BACKGROUND incidents (noise), excluding RC-06 targets ---
    seeded_n = len(incidents)
    total_target = int(seeded_n / config.SEEDED_FRACTION)
    background_n = max(0, total_target - seeded_n)
    bg_pool = [s for s in shipments["shipments"] if not getattr(s, "_rc06_target", False)]
    for _ in range(background_n):
        sh = bg_pool[int(rng.integers(0, len(bg_pool)))]
        itype = str(rng.choice(["delay", "damage", "customs_hold", "carrier_delay"]))
        incidents.append(new_incident(
            itype, str(rng.choice(["low", "medium"])), sh.planned_arrival,
            root_cause_id=None, shipment_id=sh.shipment_id))

    return {"incidents": incidents}
