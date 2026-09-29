"""
STAGE 6 — invoices (one per PO/shipment). Some become disputed, linked to incidents
created in stage 7. Amounts derive from order_items line_amounts.
"""
from __future__ import annotations
import datagen.config as config


def build_invoices(rng, reference: dict, orders: dict, shipments: dict) -> dict:
    """Return {'invoices': [...]}."""
    raise NotImplementedError
