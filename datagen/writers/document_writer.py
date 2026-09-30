"""
Persist generated documents as PLAIN JSON RECORDS (one file per document) to
artifacts/documents/, in the same shape the agent's document store reads:

    {"doc_id": ..., "doc_type": ..., "text": ..., "metadata": {...}}

The generator does NOT embed — a separate indexing step (later) can read these and push
to Qdrant. Writing plain files keeps generation deterministic and store-agnostic.

Only validated documents are written; a document that failed validation is skipped and
counted, so a bad template surfaces as a non-zero skip count rather than a silent leak.
"""
from __future__ import annotations

import json
from pathlib import Path


def write_documents(documents: list, out_dir: str) -> dict:
    """Write each validated GeneratedDocument as <doc_id>.json. Returns a small summary."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0
    for doc in documents:
        if not doc.validation_passed:
            skipped += 1
            continue
        skel = doc.skeleton
        record = {
            "doc_id": skel.doc_id,
            "doc_type": skel.doc_type,
            "text": doc.text,
            "metadata": skel.metadata,
        }
        (out / f"{skel.doc_id}.json").write_text(
            json.dumps(record, indent=2, default=str), encoding="utf-8"
        )
        written += 1

    summary = {"written": written, "skipped": skipped, "out_dir": str(out)}
    print(f"[documents] wrote {written} JSON files to {out} (skipped {skipped} unvalidated)")
    return summary
