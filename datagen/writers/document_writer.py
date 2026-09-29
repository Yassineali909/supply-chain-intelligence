"""
Persist generated documents as PLAIN RECORDS (text + metadata) to artifacts/documents/.
The generator does NOT embed — a separate indexing/ step reads these and pushes to
Qdrant. This keeps generation deterministic and lets you re-embed or swap stores
without regenerating.
"""
from __future__ import annotations
import datagen.config as config
from datagen.model import GeneratedDocument


def write(documents: list[GeneratedDocument]) -> None:
    """Serialize each document's text + queryable metadata (no embeddings)."""
    raise NotImplementedError
