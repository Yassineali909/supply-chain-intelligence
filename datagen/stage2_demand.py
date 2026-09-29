"""
STAGE 2 — monthly demand curve over the 24-month window, with the seasonal peak
(config.DEMAND_PEAK_MONTHS) that later interacts with WH-2 capacity to produce RC-04.
Demand shape drives how many POs fall in each month (stage 3).
"""
from __future__ import annotations
import datagen.config as config


def build_demand(rng) -> dict:
    """Return {month: demand_level} over the window."""
    raise NotImplementedError
