"""
STAGE 7 — incidents. Generated AFTER the delays they explain (stages 4-5), so an
incident always corresponds to a real delay.

Seeded incidents carry root_cause_id (RC-01..RC-07) and explain the levered delays.
Background incidents carry root_cause_id=None (~70% of incidents; the noise the agent
must see past). RC-06 target shipments get NO incident here — that absence is the
whole point of the refusal test.
"""
from __future__ import annotations
import datagen.config as config


def build_incidents(rng, reference: dict, shipments: dict, deliveries: dict) -> dict:
    """Return {'incidents': [...]}, seeded + background."""
    raise NotImplementedError
