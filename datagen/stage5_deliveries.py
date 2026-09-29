"""
STAGE 5 — deliveries (warehouse -> customer leg). Where the WAREHOUSE lever acts (RC-04).

The inbound shipment already arrived (stage 4, with its own delay). Now the OUTBOUND
delivery may slip further when a capacity-limited warehouse (WH-2) is hit during a
demand peak. The RC-04 signal is the ASYMMETRY: inbound shipment delay is normal, but
outbound delivery delay is elevated. A lazy agent blames the supplier; the truth is the
warehouse stage.

Each shipment yields one delivery to one customer. Customer assignment honors the RC-05
network: shipments from the RC-05 suppliers on RT-04 are spread across a set of
customers with PARTIAL overlap, so the graph question later is a real traversal.
"""
from __future__ import annotations

from datetime import timedelta

import datagen.config as config
from datagen.seed import child_stream
from datagen.model import Delivery
from datagen.levers import warehouse_lever


def build_deliveries(root, reference: dict, orders: dict, shipments: dict) -> dict:
    rng = child_stream(root, "deliveries")

    routes_by_id = {r.route_id: r for r in reference["routes"]}
    wh_by_id = {w.warehouse_id: w for w in reference["warehouses"]}
    customers = reference["customers"]
    suppliers_by_id = {s.supplier_id: s for s in reference["suppliers"]}
    po_by_id = {po.po_id: po for po in orders["purchase_orders"]}

    cust_codes = [c.customer_id for c in customers]
    rc05_pools = {}
    pool_size = 15
    starts = {"S07": 0, "S11": 8, "S19": 16, "S23": 24}
    for code, s0 in starts.items():
        pool = [cust_codes[(s0 + k) % len(cust_codes)] for k in range(pool_size)]
        rc05_pools[code] = pool

    deliveries = []
    dl_counter = 8000

    for sh in shipments["shipments"]:
        route = routes_by_id[sh.route_id]
        warehouse = wh_by_id[route.warehouse_id]
        po = po_by_id[sh.po_id]
        supplier = suppliers_by_id[po.supplier_id]

        if supplier.code in config.RC05_SUPPLIERS and route.code == "RT-04":
            pool = rc05_pools[supplier.code]
            customer_id = int(rng.choice(pool))
        else:
            customer_id = int(rng.choice(cust_codes))

        planned = sh.actual_arrival + timedelta(days=int(rng.integers(1, 4)))

        slip = warehouse_lever(warehouse, sh.planned_arrival, getattr(sh, "_is_peak", False))
        noise = max(0, round(float(rng.normal(0.3, 0.8))))
        delivery_delay = int(round(slip)) + noise

        actual = planned + timedelta(days=delivery_delay)
        status = "delivered" if delivery_delay == 0 else "late"

        dl_counter += 1
        dl = Delivery(
            delivery_id=dl_counter,
            delivery_code=f"DL-{dl_counter}",
            shipment_id=sh.shipment_id,
            customer_id=customer_id,
            warehouse_id=warehouse.warehouse_id,
            planned_date=planned,
            actual_date=actual,
            delay_days=delivery_delay,
            status=status,
        )
        dl._delay_attribution = {"warehouse": round(slip, 2), "noise": noise}
        deliveries.append(dl)

    return {"deliveries": deliveries}
