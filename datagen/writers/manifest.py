"""
STAGE 12 — write artifacts/generation_manifest.json.

Records reproducibility (version, seed, timestamp) and COVERAGE (total counts plus
per-scenario incident and document counts). The per-scenario counts are mandatory:
when a scenario later underperforms, the first diagnostic question is "did enough
evidence get generated?" — and this file answers it without a manual query, exactly
the ambiguity that cost time in the GDPR project (stale index vs real failure).
"""
from __future__ import annotations

import datagen.config as config


def write_manifest(dataset: dict, documents: list) -> dict:
    """
    Compute and serialize the manifest. Returns the counts dict so the evidence-floor
    check can reuse it. Shape:

        {
          "generator_version": ..., "seed": ..., "generated_at": ...,
          "counts": {suppliers, purchase_orders, shipments, deliveries, incidents, documents},
          "incident_counts_by_root_cause": {RC-01..RC-07, BACKGROUND},
          "document_counts_by_root_cause":  {RC-01..RC-07, BACKGROUND}
        }
    """
    raise NotImplementedError
