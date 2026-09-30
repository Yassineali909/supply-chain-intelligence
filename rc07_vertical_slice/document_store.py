from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class DocumentStoreError(RuntimeError):
    pass


def _load_documents(root: Path) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    if not root.exists():
        raise DocumentStoreError(f"Document root does not exist: {root}")
    for path in sorted(root.glob("*.json")):
        with path.open("r", encoding="utf-8") as f:
            docs.append(json.load(f))
    return docs


def search_documents(root: str | Path, shipment_code: str, *, evidence_id: str = "EVD-002", trace_call_id: str = "TC-002") -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    docs = _load_documents(Path(root))
    matches: list[dict[str, Any]] = []
    for doc in docs:
        text = str(doc.get("text", ""))
        metadata = doc.get("metadata", {})
        if shipment_code in text or metadata.get("shipment_code") == shipment_code:
            matches.append(doc)

    matches.sort(key=lambda d: str(d.get("doc_id", "")))
    selected = matches[:5]
    trace = {
        "tool_call_id": trace_call_id,
        "tool": "search_documents",
        "purpose": "find operational documents that directly mention the shipment",
        "status": "SUCCESS",
        "input": {"shipment_code": shipment_code},
        "result_summary": {"matched": len(matches), "returned": len(selected)},
    }
    if not selected:
        return [], trace, evidence_id

    return selected, trace, evidence_id
