"""
build_qdrant_index.py — index the real document corpus into on-disk Qdrant with a local
Ollama embedder, then PROVE the exact-lookup path is safe to migrate before anything is
wired in.

Prereqs:
    pip install qdrant-client
    ollama pull nomic-embed-text
Run:
    cd rc07_vertical_slice && python build_qdrant_index.py

What it does, in order:
  1. Loads every JSON doc from artifacts/documents (via the existing JSON loader).
  2. Embeds each doc's text with Ollama nomic-embed-text and upserts into ./qdrant_data.
  3. PARITY GATE: for a sample of real shipment codes AND the 5 known RC-06 shipments,
     confirms Qdrant's exact lookup returns the SAME doc_ids as the JSON store — and that
     the RC-06 shipments return EMPTY in both (the honest-refusal signal). This is the
     safety check that must pass before search_documents is ever pointed at Qdrant.
  4. Demonstrates semantic search (the new capability) on a couple of content queries.

Nothing here wires Qdrant into the investigations. Migration happens only after the parity
gate is green on real data.
"""
from __future__ import annotations

import re
from pathlib import Path

from document_store import _load_documents, search_documents as json_search
from qdrant_store import QdrantDocumentStore, make_ollama_embedder

DOC_ROOT = "../artifacts/documents"
QDRANT_PATH = "./qdrant_data"

# Known RC-06 shipments for the current seed (handoff): they have CONTEXTUAL docs but NO
# DIRECT doc -> the exact lookup must return EMPTY, which is what RC-06's refusal relies on.
RC06_CODES = ["SH-4493", "SH-5268", "SH-5761", "SH-6010", "SH-6259"]

_CODE_RE = re.compile(r"\bSH-\d+\b")


def main() -> int:
    root = Path(DOC_ROOT)
    print(f"loading documents from {root.resolve()} ...")
    docs = _load_documents(root)
    print(f"  {len(docs)} documents")

    embed = make_ollama_embedder("nomic-embed-text")
    print("probing embedding dimension (nomic-embed-text) ...")
    dim = len(embed(["dimension probe"])[0])
    print(f"  vector size = {dim}")

    store = QdrantDocumentStore.on_disk(QDRANT_PATH, embed, vector_size=dim)
    print(f"embedding + indexing {len(docs)} docs into {QDRANT_PATH} "
          f"(Ollama embeds one at a time — this takes a few minutes) ...")
    n = store.index(docs)
    print(f"  indexed {n} points")

    # ---- PARITY GATE ----------------------------------------------------------------
    print("\n=== PARITY GATE: Qdrant exact lookup vs JSON store ===")
    # sample real codes that actually appear in the corpus metadata
    present = []
    for d in docs:
        c = (d.get("metadata") or {}).get("shipment_code")
        if c and c not in present:
            present.append(c)
        if len(present) >= 15:
            break

    mismatches = 0
    for code in present:
        j = [d.get("doc_id") for d in json_search(root, code)[0]]
        q = [d.get("doc_id") for d in store.search_documents(code)[0]]
        ok = j == q
        mismatches += (not ok)
        if not ok:
            print(f"  MISMATCH {code}: json={j} qdrant={q}")
    print(f"  present-code parity: {len(present) - mismatches}/{len(present)} match")

    print("  RC-06 shipments (must be EMPTY in both -> honest refusal preserved):")
    rc06_ok = 0
    for code in RC06_CODES:
        j = json_search(root, code)[0]
        q = store.search_documents(code)[0]
        empty_both = (len(j) == 0 and len(q) == 0)
        rc06_ok += empty_both
        print(f"    {code}: json={len(j)} qdrant={len(q)}  {'OK' if empty_both else '**CHECK**'}")

    gate = (mismatches == 0 and rc06_ok == len(RC06_CODES))
    print(f"\nPARITY GATE: {'PASS — safe to migrate search_documents to Qdrant' if gate else 'FAIL — do NOT migrate; investigate mismatches'}")

    # ---- semantic search demo (new capability) --------------------------------------
    print("\n=== SEMANTIC SEARCH (new capability) ===")
    for query in ["customs hold at the port", "carrier was late repeatedly"]:
        print(f"\nquery: {query!r}")
        for doc, score in store.semantic_search(query, top_k=3):
            snippet = str(doc.get("text", ""))[:80].replace("\n", " ")
            print(f"  {score:.3f}  {doc.get('doc_id')}  {snippet}")

    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
