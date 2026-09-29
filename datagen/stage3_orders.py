"""
STAGE 3 — purchase_orders + order_items, drawn across the 24-month window.

Beyond producing ~N_PURCHASE_ORDERS orders, this stage sets up the route exposure that
later scenarios depend on. It does NOT assign routes to shipments (that is stage 4) —
but it DOES decide, per PO, an intended route so that:

  * S07 (RC-02) gets a controlled MIX: enough POs intended for CLEAN (non-PORT-GEN)
    routes to support the clean-route peer comparison, plus some on PORT-GEN routes.
  * The RC-05 network suppliers (S07/S11/S19/S23) get enough volume intended for the
    shared RT-04 lane.

We attach the intended route on the PO via a private field so stage 4 can honor it
without re-deciding. Everything else is seeded-random.

Simple inline demand model: POs are spread across the window with a mild seasonal
bump in the peak months (config.DEMAND_PEAK_MONTHS), which later interacts with WH-2
capacity (RC-04). A richer curve can move to stage2_demand.py later.
"""
from __future__ import annotations

from datetime import date, timedelta

import datagen.config as config
from datagen.seed import child_stream
from datagen.model import PurchaseOrder, OrderItem


def _window_days() -> tuple:
    """Return (start_date, end_date) of the 24-month operating window."""
    end = date.fromisoformat(config.END_DATE)
    start = date(end.year - 2, end.month, 1)
    return start, end


def _peak_months() -> set:
    """Return the set of 'YYYY-MM' strings that are demand peaks."""
    return set(config.DEMAND_PEAK_MONTHS)


def build_orders(root, reference: dict) -> dict:
    """
    Return {'purchase_orders': [...], 'order_items': [...]}.
    Each PO carries a private _intended_route_code for stage 4 to honor.
    """
    rng = child_stream(root, "orders")
    start, end = _window_days()
    total_days = (end - start).days

    suppliers = reference["suppliers"]
    products = reference["products"]
    routes = reference["routes"]
    contracts_by_supplier = {c.supplier_id: c for c in reference["supplier_contracts"]}

    portgen_port_id = [p.port_id for p in reference["ports"] if p.code == "PORT-GEN"][0]
    portgen_routes = [r.code for r in routes if r.port_id == portgen_port_id]
    clean_routes = [r.code for r in routes if r.port_id != portgen_port_id]
    rt04 = "RT-04"

    def route_for(supplier_code: str) -> str:
        """Pick an intended route for a PO, honoring scenario exposure requirements."""
        if supplier_code == "S07":
            if rng.random() < 0.60:
                return str(rng.choice(clean_routes))
            return str(rng.choice(portgen_routes))
        if supplier_code in config.RC05_SUPPLIERS:
            if rng.random() < 0.45:
                return rt04
            return str(rng.choice([r.code for r in routes]))
        return str(rng.choice([r.code for r in routes]))

    purchase_orders = []
    order_items = []
    po_counter = 10000
    item_counter = 1

    weights = []
    for s in suppliers:
        if s.code == "S07":
            weights.append(4.0)
        elif s.code in config.RC05_SUPPLIERS:
            weights.append(3.0)
        else:
            weights.append(1.0)
    weights = [w / sum(weights) for w in weights]

    for _ in range(config.N_PURCHASE_ORDERS):
        s = suppliers[int(rng.choice(len(suppliers), p=weights))]
        offset = int(rng.integers(0, total_days))
        order_date = start + timedelta(days=offset)
        ym = f"{order_date.year}-{order_date.month:02d}"
        contract = contracts_by_supplier[s.supplier_id]
        promised = order_date + timedelta(days=contract.agreed_lead_days)

        po_counter += 1
        po = PurchaseOrder(
            po_id=po_counter,
            po_code=f"PO-{po_counter}",
            supplier_id=s.supplier_id,
            order_date=order_date,
            promised_date=promised,
            status="fulfilled",
        )
        po._intended_route_code = route_for(s.code)
        po._peak = ym in _peak_months()
        purchase_orders.append(po)

        n_items = int(rng.integers(1, 5))
        for _ in range(n_items):
            prod = products[int(rng.integers(0, len(products)))]
            qty = int(rng.integers(1, 200))
            order_items.append(OrderItem(
                item_id=item_counter,
                po_id=po.po_id,
                product_id=prod.product_id,
                quantity=qty,
                line_amount=round(qty * prod.unit_cost, 2),
            ))
            item_counter += 1

    return {"purchase_orders": purchase_orders, "order_items": order_items}
