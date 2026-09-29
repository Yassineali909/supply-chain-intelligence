"""
STAGE 5 — deliveries (warehouse -> customer leg). Where the WAREHOUSE lever acts (RC-04).

Inbound shipment arrived (stage 4); now the outbound delivery may slip when a
capacity-limited warehouse (WH-2) is hit during the demand peak. This asymmetry —
inbound normal, outbound late — is the RC-04 stage-localization trap and is asserted
by the evidence floor.
"""
from __future__ import annotations
import datagen.config as config


def build_deliveries(rng, reference: dict, shipments: dict, demand: dict) -> dict:
    """Return {'deliveries': [...]} with warehouse slip applied at the delivery stage."""
    raise NotImplementedError
