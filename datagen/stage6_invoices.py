"""
STAGE 6 — invoices (one per PO). Amounts derive from the PO's order_items. A minority
are disputed; disputes will be linked to incidents in stage 7 where applicable. Payment
timing is seeded-random around the due date.
"""
from __future__ import annotations

from datetime import timedelta

import datagen.config as config
from datagen.seed import child_stream
from datagen.model import Invoice


def build_invoices(root, reference: dict, orders: dict) -> dict:
    rng = child_stream(root, "invoices")

    items_by_po = {}
    for it in orders["order_items"]:
        items_by_po.setdefault(it.po_id, []).append(it)

    invoices = []
    inv_counter = 22000

    for po in orders["purchase_orders"]:
        amount = round(sum(it.line_amount for it in items_by_po.get(po.po_id, [])), 2)
        issued = po.order_date + timedelta(days=int(rng.integers(1, 10)))
        due = issued + timedelta(days=30)

        r = rng.random()
        if r < 0.85:
            paid = due + timedelta(days=int(rng.integers(-5, 15)))
            disputed = False
            status = "paid"
        elif r < 0.90:
            paid = None
            disputed = True
            status = "disputed"
        else:
            paid = None
            disputed = False
            status = "unpaid"

        inv_counter += 1
        invoices.append(Invoice(
            invoice_id=inv_counter,
            invoice_code=f"INV-{inv_counter}",
            po_id=po.po_id,
            amount=amount,
            issued_date=issued,
            due_date=due,
            paid_date=paid,
            disputed=disputed,
            status=status,
        ))

    return {"invoices": invoices}
