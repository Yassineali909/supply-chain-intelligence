"""
document_retrieval.py — a thin backend switch for document search.

Exposes search_documents() with the EXACT signature and return shape the investigations
already call (rc07.py, planner.py), so swapping it in is a one-line import change and every
existing test stays green.

Backend selection (opt-in, reversible, deterministic by default):
  * default (no env var)        -> the JSON directory store (document_store.search_documents)
  * USE_QDRANT=1 + index present -> the Qdrant payload-filter exact lookup (RC-06-safe)
If USE_QDRANT=1 is set but the index or qdrant-client is missing, it falls back to JSON and
says so once on stderr, rather than failing — the investigation never breaks over a backend.

Why the Qdrant path is safe here: it uses the EXACT payload filter (whole shipment code),
not vector similarity, so an absent shipment returns [] exactly as the JSON store does —
the empty result RC-06's honest refusal depends on. Proven by the parity gate in
build_qdrant_index.py on the real corpus.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from document_store import search_documents as _json_search

_QDRANT_PATH = os.environ.get("QDRANT_PATH", "./qdrant_data")
_EMBED_MODEL = os.environ.get("QDRANT_EMBED_MODEL", "nomic-embed-text")

_store = None            # cached QdrantDocumentStore
_warned = False


def _qdrant_enabled() -> bool:
    return os.environ.get("USE_QDRANT", "") == "1"


def _warn_once(msg: str) -> None:
    global _warned
    if not _warned:
        print(f"[document_retrieval] {msg} — falling back to JSON store.", file=sys.stderr)
        _warned = True


def _get_store():
    """Lazily open the on-disk Qdrant store, or None if unavailable."""
    global _store
    if _store is not None:
        return _store
    if not Path(_QDRANT_PATH).exists():
        _warn_once(f"USE_QDRANT=1 but no index at {_QDRANT_PATH}")
        return None
    try:
        from qdrant_store import QdrantDocumentStore, make_ollama_embedder
        embed = make_ollama_embedder(_EMBED_MODEL)
        dim = len(embed(["dimension probe"])[0])
        _store = QdrantDocumentStore.on_disk(_QDRANT_PATH, embed, vector_size=dim)
        return _store
    except Exception as exc:  # qdrant-client missing, ollama down, etc.
        _warn_once(f"could not open Qdrant store ({type(exc).__name__}: {exc})")
        return None


def search_documents(root: str | Path, shipment_code: str, *,
                     evidence_id: str = "EVD-002", trace_call_id: str = "TC-002"
                     ) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    """Identical interface to document_store.search_documents; routes to the chosen backend.

    The exact-lookup semantics are preserved on both paths (an absent shipment -> []),
    so RC-06's refusal is unaffected regardless of backend.
    """
    if _qdrant_enabled():
        store = _get_store()
        if store is not None:
            return store.search_documents(
                shipment_code, evidence_id=evidence_id, trace_call_id=trace_call_id)
    return _json_search(root, shipment_code,
                        evidence_id=evidence_id, trace_call_id=trace_call_id)
