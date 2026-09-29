"""
STAGE 10 — factual document skeletons (deterministic).

For each document, pull the exact codes/dates/numbers it must contain from structured
rows. Direct-evidence docs get root_cause_id in metadata; CONTEXT-noise docs (RC-06)
get root_cause_id=None in metadata — their scenario association is recorded only in the
answer key's context_for. This split is what keeps the refusal test honest.
"""
from __future__ import annotations
import datagen.config as config
from datagen.model import DocumentSkeleton


def build_skeletons(dataset: dict, scenarios: list) -> list[DocumentSkeleton]:
    """Return the full list of document skeletons (direct + context + background)."""
    raise NotImplementedError
