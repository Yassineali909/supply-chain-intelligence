"""
Persist the structured source of truth to PostgreSQL (stages 1-8). This is the ONLY
authoritative store; graph, documents and embeddings are projections built after.

Writes the agent-visible schema WITHOUT the hidden lever columns (reliability_tier,
perf_trend, congestion_season) — those are kept for verification but must not reach the
agent's text-to-SQL view. Provide a separate curated view for the agent.
"""
from __future__ import annotations
import datagen.config as config


def write(dataset: dict) -> None:
    """Create tables and bulk-insert all structured rows deterministically."""
    raise NotImplementedError
