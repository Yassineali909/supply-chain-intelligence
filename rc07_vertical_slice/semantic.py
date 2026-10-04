"""
semantic.py — the `doc_search` route: answer document-CONTENT questions via Qdrant semantic
search, Option A style.

"What do our documents say about customs holds?" has no ground-truth number and invites the
classic RAG failure: the model asserting things the documents don't support. So the model
does NOT write the answer here. Vectors RETRIEVE; deterministic code REPORTS exactly what was
retrieved (doc ids, snippets, similarity scores); the claim is a RELATIONSHIP claim ("these
documents relate to this query"), which the verifier gates by evidence-binding without ever
asserting causation. Retrieved docs are CONTEXTUAL (semantic similarity is not causal proof —
cf. D7). Below a similarity floor it REFUSES rather than return the nearest-but-irrelevant doc
(the semantic analogue of RC-06).

This is the one capability the JSON store could never do; it requires the Qdrant index. If the
index is absent, the investigation refuses with a clear message instead of failing.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from agent_contract import (
    AgentResponse, Claim, ClaimType, Evidence, Outcome, Relevance,
    SourceType, SupportStatus, Timing, ToolTraceEntry, Verification,
)
from verifier import verify_response

TOP_K = 5
SCORE_FLOOR = 0.55         # measured: on-topic >=0.72, off-topic <=0.40 (gap is wide); 0.55 sits in it
SNIPPET = 140

_SHIPMENT_RE = re.compile(r"\bSH-\d+\b")
_DOC_NOUN_RE = re.compile(r"\b(documents?|docs|reports?|incident reports?|records?)\b", re.IGNORECASE)
_DOC_VERB_RE = re.compile(r"\b(say|says|said|mention|mentions|mentioning|about|regarding|"
                          r"discuss|discusses|describe|describes|find|search|related to)\b",
                          re.IGNORECASE)


def is_doc_search_question(question: str) -> bool:
    """Document-CONTENT question (not a specific-shipment lookup, not an aggregate)."""
    if _SHIPMENT_RE.search(question):      # a specific shipment -> RC-07 owns it
        return False
    return bool(_DOC_NOUN_RE.search(question) and _DOC_VERB_RE.search(question))


def _run_id() -> str:
    return "RUN-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _default_store():
    """Open the on-disk Qdrant store with the Ollama embedder, or None if no index."""
    path = os.environ.get("QDRANT_PATH", "./qdrant_data")
    if not Path(path).exists():
        return None
    try:
        from qdrant_store import QdrantDocumentStore, make_ollama_embedder
        embed = make_ollama_embedder(os.environ.get("QDRANT_EMBED_MODEL", "nomic-embed-text"))
        dim = len(embed(["dimension probe"])[0])
        return QdrantDocumentStore.on_disk(path, embed, vector_size=dim)
    except Exception:
        return None


def _refuse(question, answer, started):
    return AgentResponse(
        run_id=_run_id(), question=question, outcome=Outcome.INSUFFICIENT_EVIDENCE,
        answer=answer, claims=[], evidence=[], tool_trace=[],
        verification=Verification(status="FAILED", checks=[]),
        timing=Timing(total_ms=int((time.perf_counter() - started) * 1000)))


def investigate_doc_search(question: str, *, store=None, top_k: int = TOP_K,
                           score_floor: float = SCORE_FLOOR) -> AgentResponse:
    started = time.perf_counter()
    store = store if store is not None else _default_store()
    if store is None:
        return _refuse(question,
                       "Semantic document search requires the Qdrant index. Build it with "
                       "`python build_qdrant_index.py`, then retry.", started)

    t0 = time.perf_counter()
    hits = store.semantic_search(question, top_k=top_k)
    tool_ms = int((time.perf_counter() - t0) * 1000)

    relevant = [(doc, score) for doc, score in hits if score >= score_floor]
    if not relevant:
        best = max((s for _, s in hits), default=0.0)
        return _refuse(question,
                       f"No documents in the corpus are sufficiently relevant to this query "
                       f"(best similarity {best:.2f} < {score_floor}). Refusing rather than "
                       f"return an unrelated document.", started)

    evidences, refs = [], []
    for i, (doc, score) in enumerate(relevant):
        eid = f"EVD-{i}"
        refs.append(eid)
        doc_id = str(doc.get("doc_id", f"doc-{i}"))
        snippet = str(doc.get("text", "")).replace("\n", " ")[:SNIPPET]
        evidences.append(Evidence(
            evidence_id=eid, source_type=SourceType.DOCUMENT, source_ref="qdrant:documents",
            locator={"doc_id": doc_id, "score": round(float(score), 4)},
            fact=f"Document {doc_id} (similarity {score:.2f}) is relevant to the query: {snippet}",
            relevance=Relevance.CONTEXTUAL))

    claim = Claim(
        claim_id="CLM-DOC",
        text=f"{len(relevant)} documents in the corpus are semantically relevant to this query.",
        claim_type=ClaimType.RELATIONSHIP, support_status=SupportStatus.SUPPORTED,
        evidence_ids=refs)

    lines = "\n".join(
        f"  - {e.locator['doc_id']} (score {e.locator['score']:.2f}): "
        f"{str(d.get('text','')).splitlines()[0][:100] if str(d.get('text',''))  else ''}"
        for e, (d, _) in zip(evidences, relevant))
    answer = (
        f"{len(relevant)} document(s) in the corpus are relevant to your query:\n{lines}\n"
        f"(Ranked by semantic similarity. This reports which documents match; it deliberately "
        f"does not synthesize or assert a causal conclusion beyond what the documents are.)")

    trace = [ToolTraceEntry(
        step=1, tool_call_id="TC-SEM", tool="search_documents",
        purpose="semantic search over the document corpus", status="SUCCESS",
        input={"query": question, "top_k": top_k, "score_floor": score_floor},
        output_refs=refs)]

    resp = AgentResponse(
        run_id=_run_id(), question=question, outcome=Outcome.SUPPORTED, answer=answer,
        claims=[claim], evidence=evidences, tool_trace=trace,
        verification=Verification(status="FAILED", checks=[]),
        timing=Timing(total_ms=int((time.perf_counter() - started) * 1000), tool_ms=tool_ms))
    verified = verify_response(resp)
    verified.tool_trace.append(ToolTraceEntry(
        step=2, tool_call_id="TC-VERIFY", tool="verify_evidence",
        purpose="bind the relationship claim to the retrieved documents",
        status="SUCCESS" if verified.verification.status == "PASSED" else "ERROR",
        input={"claim_ids": ["CLM-DOC"]}, output_refs=[]))
    return verified
