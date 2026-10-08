"""
qdrant_store.py - a Qdrant-backed document store that does TWO things, deliberately kept
separate:

  1. EXACT lookup by shipment code (lookup_by_code / search_documents) - a drop-in for the
     JSON store's search_documents, implemented with a Qdrant PAYLOAD FILTER, not vector
     similarity. This preserves the exactness RC-06 depends on: when no document mentions a
     shipment, the lookup returns [] and the honest INSUFFICIENT_EVIDENCE refusal stands.
     A fuzzy/semantic search here would return the nearest doc even when none is relevant,
     silently breaking that refusal - so it is intentionally NOT used for this path.

  2. SEMANTIC search (semantic_search) - a genuinely NEW capability: vector similarity over
     document text, for content questions the exact lookup can't answer ("what do our docs
     say about customs holds?"). This is additive; it does not touch the exact-lookup path.

The embedding function is INJECTED (embed_fn(texts) -> vectors), so the store logic is
testable with a deterministic fake and runs on a real local model (Ollama nomic-embed-text)
in production. Nothing here needs a running Qdrant server: QdrantClient(":memory:") or an
on-disk path both work with no daemon.

NOTE on exactness vs the JSON store: the JSON store matched `code in text` (a SUBSTRING
match, so "SH-1" also matched "SH-10"). This store matches WHOLE codes (whole-code matching
plus metadata.shipment_code), which is more correct. For real queries (full codes) the
results are identical; the included parity checker confirms this on the real corpus before
anything is migrated.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Callable, Iterable

from qdrant_client import QdrantClient, models

EmbedFn = Callable[[list[str]], list[list[float]]]

_SHIPMENT_CODE_RE = re.compile(r"\bSH-\d+\b")


def _default_ollama_host() -> str:
    import os
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def _codes_in(doc: dict[str, Any]) -> list[str]:
    """Whole shipment codes a document refers to: those in its text + its metadata code."""
    text = str(doc.get("text", ""))
    codes = set(_SHIPMENT_CODE_RE.findall(text))
    meta_code = (doc.get("metadata") or {}).get("shipment_code")
    if meta_code:
        codes.add(str(meta_code))
    return sorted(codes)


class QdrantDocumentStore:
    def __init__(self, client: QdrantClient, embed_fn: EmbedFn, vector_size: int,
                 collection: str = "documents"):
        self.client = client
        self.embed_fn = embed_fn
        self.vector_size = vector_size
        self.collection = collection

    # --- construction ---------------------------------------------------------------
    @classmethod
    def in_memory(cls, embed_fn: EmbedFn, vector_size: int, collection: str = "documents"):
        return cls(QdrantClient(":memory:"), embed_fn, vector_size, collection)

    @classmethod
    def on_disk(cls, path: str, embed_fn: EmbedFn, vector_size: int, collection: str = "documents"):
        return cls(QdrantClient(path=path), embed_fn, vector_size, collection)

    @classmethod
    def on_url(cls, url: str, embed_fn: EmbedFn, vector_size: int, collection: str = "documents"):
        # Qdrant SERVER mode (Docker stack): a shared daemon multiple containers can reach.
        return cls(QdrantClient(url=url), embed_fn, vector_size, collection)

    def _ensure_collection(self, recreate: bool = False) -> None:
        exists = self.client.collection_exists(self.collection)
        if exists and recreate:
            self.client.delete_collection(self.collection)
            exists = False
        if not exists:
            self.client.create_collection(
                self.collection,
                vectors_config=models.VectorParams(
                    size=self.vector_size, distance=models.Distance.COSINE),
            )

    # --- indexing ---------------------------------------------------------------------
    def index(self, docs: Iterable[dict[str, Any]], *, recreate: bool = True,
              batch_size: int = 128) -> int:
        """Embed and upsert documents. Stores the whole doc in the payload (so lookups
        return the original shape) plus a `codes` field for exact filtering."""
        self._ensure_collection(recreate=recreate)
        docs = list(docs)
        n = 0
        for start in range(0, len(docs), batch_size):
            chunk = docs[start:start + batch_size]
            vectors = self.embed_fn([str(d.get("text", "")) for d in chunk])
            points = []
            for j, (doc, vec) in enumerate(zip(chunk, vectors)):
                points.append(models.PointStruct(
                    id=start + j,
                    vector=list(vec),
                    payload={"doc": doc, "codes": _codes_in(doc),
                             "doc_id": str(doc.get("doc_id", start + j))},
                ))
            self.client.upsert(self.collection, points)
            n += len(points)
        return n

    # --- EXACT lookup (RC-06-preserving) ---------------------------------------------
    def lookup_by_code(self, shipment_code: str, limit: int = 5) -> list[dict[str, Any]]:
        """Documents that mention this exact shipment code. Empty if none - which is the
        signal RC-06 relies on. No vector similarity involved."""
        flt = models.Filter(must=[models.FieldCondition(
            key="codes", match=models.MatchValue(value=shipment_code))])
        hits = self.client.scroll(self.collection, scroll_filter=flt,
                                   limit=1000, with_payload=True)[0]
        docs = [h.payload["doc"] for h in hits]
        docs.sort(key=lambda d: str(d.get("doc_id", "")))
        return docs[:limit]

    def search_documents(self, shipment_code: str, *, evidence_id: str = "EVD-002",
                         trace_call_id: str = "TC-002"
                         ) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
        """Drop-in for document_store.search_documents: identical return shape, backed by
        the Qdrant payload filter instead of a JSON directory scan."""
        selected = self.lookup_by_code(shipment_code)
        trace = {
            "tool_call_id": trace_call_id,
            "tool": "search_documents",
            "purpose": "find operational documents that directly mention the shipment",
            "status": "SUCCESS",
            "input": {"shipment_code": shipment_code},
            "result_summary": {"matched": len(selected), "returned": len(selected)},
        }
        return selected, trace, evidence_id

    # --- SEMANTIC search (new capability) --------------------------------------------
    def semantic_search(self, query: str, top_k: int = 5) -> list[tuple[dict[str, Any], float]]:
        """Vector similarity over document text. For content questions, NOT for the
        exact shipment lookup (which must stay exact)."""
        qvec = self.embed_fn([query])[0]
        res = self.client.query_points(self.collection, query=list(qvec),
                                        limit=top_k, with_payload=True).points
        return [(p.payload["doc"], float(p.score)) for p in res]


# ---------------------------------------------------------------------------
# Embedders
# ---------------------------------------------------------------------------

def hashing_embedder(dim: int = 32) -> EmbedFn:
    """Deterministic, model-free embedder for EXACT-lookup tests (semantics irrelevant)."""
    def embed(texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            vec = [((h[i % len(h)] / 255.0) * 2 - 1) for i in range(dim)]
            out.append(vec)
        return out
    return embed


def bag_of_words_embedder(vocab: list[str]) -> EmbedFn:
    """Deterministic term-frequency embedder over a fixed vocabulary - gives MEANINGFUL
    semantic ranking in tests without any model (a 'customs delay' query lands nearest the
    doc about customs delays)."""
    vocab = [w.lower() for w in vocab]

    def embed(texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            tl = t.lower()
            vec = [float(tl.count(w)) for w in vocab]
            # add a tiny constant so an all-zero text still yields a valid (non-NaN) cosine
            vec = [v + 1e-6 for v in vec]
            out.append(vec)
        return out
    return embed


def make_ollama_embedder(model: str = "nomic-embed-text",
                         host: str = None) -> EmbedFn:
    """Real local embedder via Ollama. Requires `ollama pull nomic-embed-text` (768-dim).
    Tries the `ollama` python package, falls back to the REST API."""
    def embed(texts: list[str]) -> list[list[float]]:
        vectors = []
        try:
            import ollama  # type: ignore
            for t in texts:
                r = ollama.embeddings(model=model, prompt=t)
                vectors.append(list(r["embedding"]))
            return vectors
        except Exception:
            import json as _json
            import urllib.request
            for t in texts:
                req = urllib.request.Request(
                    f"{(host or _default_ollama_host()).rstrip('/')}/api/embeddings",
                    data=_json.dumps({"model": model, "prompt": t}).encode(),
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req) as resp:
                    vectors.append(list(_json.loads(resp.read())["embedding"]))
            return vectors
    return embed
