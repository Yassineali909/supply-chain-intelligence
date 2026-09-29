"""
STAGE 8 — supplier_performance rollup. PURE AGGREGATION of stages 3-7.

Per supplier, per month (keyed on the PO order month), compute:
  orders_count     — POs placed that month
  on_time_count    — shipments that arrived with delay_days <= 0
  avg_delay_days   — mean shipment delay_days
  sla_breach_count — shipments whose actual lead time exceeded the contract lead time

INVARIANT: this table is a CONVENIENCE/SPEED materialization. It must be reconstructable
by a single GROUP BY over the base tables (purchase_orders + shipments + contracts). It
is never an independent fact. build_performance() and the equivalent SQL must agree.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

import datagen.config as config
from datagen.model import SupplierPerformance


def _month_key(d: date) -> date:
    """First-of-month bucket for a date."""
    return date(d.year, d.month, 1)


def build_performance(reference: dict, orders: dict, shipments: dict) -> dict:
    """
    Return {'supplier_performance': [...]}. Pure aggregation — no RNG, deterministic by
    construction. Keyed by (supplier_id, month) where month is the PO's order month.
    """
    po_by_id = {po.po_id: po for po in orders["purchase_orders"]}
    contract_by_supplier = {c.supplier_id: c for c in reference["supplier_contracts"]}

    buckets = defaultdict(list)
    for sh in shipments["shipments"]:
        po = po_by_id[sh.po_id]
        key = (po.supplier_id, _month_key(po.order_date))
        buckets[key].append((sh, po))

    rows = []
    for (supplier_id, month), pairs in sorted(buckets.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        contract = contract_by_supplier[supplier_id]
        orders_count = len(pairs)
        on_time = sum(1 for sh, _ in pairs if sh.delay_days <= 0)
        avg_delay = sum(sh.delay_days for sh, _ in pairs) / orders_count
        sla_breaches = 0
        for sh, po in pairs:
            actual_lead = (sh.actual_arrival - po.order_date).days
            if actual_lead > contract.agreed_lead_days:
                sla_breaches += 1
        rows.append(SupplierPerformance(
            supplier_id=supplier_id,
            period_month=month,
            orders_count=orders_count,
            on_time_count=on_time,
            avg_delay_days=round(avg_delay, 2),
            sla_breach_count=sla_breaches,
        ))

    return {"supplier_performance": rows}
