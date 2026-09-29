"""
STAGE 8 — supplier_performance rollup. PURE AGGREGATION of stages 4-7; must be
reproducible by a single SQL GROUP BY. Exists for convenience/speed only, never as an
independent fact. If it can't be re-derived from the base tables, it's wrong.
"""
from __future__ import annotations
import datagen.config as config


def build_performance(dataset: dict) -> dict:
    """Return {'supplier_performance': [...]} aggregated per supplier per month."""
    raise NotImplementedError
