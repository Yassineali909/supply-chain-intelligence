"""
Tests for the Qdrant-backed document store. Hermetic: QdrantClient(":memory:") and injected
deterministic embedders — no server, no model download. Uses the real JSON store as the
parity oracle for the exact-lookup path, and proves RC-06's empty-result behavior survives.
"""
import json
from pathlib import Path

import pytest

from document_store import search_documents as json_search
from qdrant_store import (
    QdrantDocumentStore, hashing_embedder, bag_of_words_embedder,
)

DOCS = [
    {"doc_id": "D1", "text": "Report on SH-100 customs hold", "relevance": "DIRECT",
     "metadata": {"shipment_code": "SH-100"}},
    {"doc_id": "D2", "text": "Weather note mentioning SH-200", "relevance": "DIRECT",
     "metadata": {"shipment_code": "SH-200"}},
    {"doc_id": "D3", "text": "General note, no shipment referenced", "relevance": "CONTEXTUAL",
     "metadata": {}},
    {"doc_id": "D4", "text": "Follow-up about SH-100 clearance", "relevance": "DIRECT",
     "metadata": {"shipment_code": "SH-100"}},
]


@pytest.fixture
def json_root(tmp_path):
    for d in DOCS:
        (tmp_path / f"{d['doc_id']}.json").write_text(json.dumps(d), encoding="utf-8")
    return tmp_path


@pytest.fixture
def qstore():
    store = QdrantDocumentStore.in_memory(hashing_embedder(16), vector_size=16)
    store.index(DOCS)
    return store


# --- exact lookup: parity with the JSON store ------------------------------------------

def test_exact_lookup_matches_json_store(json_root, qstore):
    for code in ["SH-100", "SH-200"]:
        j_docs, _, _ = json_search(json_root, code)
        q_docs, _, _ = qstore.search_documents(code)
        assert [d["doc_id"] for d in j_docs] == [d["doc_id"] for d in q_docs], code


def test_absent_code_returns_empty_both_stores_rc06(json_root, qstore):
    # RC-06 integrity: no document for a shipment -> empty -> honest refusal upstream.
    j_docs, _, _ = json_search(json_root, "SH-999")
    q_docs, q_trace, q_eid = qstore.search_documents("SH-999")
    assert j_docs == [] and q_docs == []
    assert q_trace["result_summary"]["matched"] == 0
    assert q_eid == "EVD-002"


def test_search_documents_trace_shape(qstore):
    docs, trace, eid = qstore.search_documents("SH-100", evidence_id="EVD-X", trace_call_id="TC-X")
    assert {d["doc_id"] for d in docs} == {"D1", "D4"}
    assert trace["tool"] == "search_documents" and trace["status"] == "SUCCESS"
    assert trace["input"] == {"shipment_code": "SH-100"}
    assert eid == "EVD-X"


def test_whole_code_match_fixes_json_substring_overmatch():
    # The JSON store does `code in text`, so "SH-1" over-matches "SH-100"/"SH-10". The
    # Qdrant store matches WHOLE codes, which is correct. This documents the (improving)
    # difference explicitly rather than hiding it.
    store = QdrantDocumentStore.in_memory(hashing_embedder(16), vector_size=16)
    store.index([
        {"doc_id": "A", "text": "about SH-1", "metadata": {"shipment_code": "SH-1"}},
        {"doc_id": "B", "text": "about SH-100", "metadata": {"shipment_code": "SH-100"}},
    ])
    assert [d["doc_id"] for d in store.lookup_by_code("SH-1")] == ["A"]      # not B
    assert [d["doc_id"] for d in store.lookup_by_code("SH-100")] == ["B"]


# --- semantic search: new capability ---------------------------------------------------

def test_semantic_search_ranks_relevant_doc_first():
    vocab = ["customs", "weather", "strike", "delay", "port"]
    store = QdrantDocumentStore.in_memory(bag_of_words_embedder(vocab), vector_size=len(vocab))
    store.index([
        {"doc_id": "CUST", "text": "customs hold caused the delay, customs paperwork"},
        {"doc_id": "WX", "text": "weather storm closed the port"},
        {"doc_id": "STRIKE", "text": "labor strike at the port, strike ongoing"},
    ])
    top_doc, score = store.semantic_search("customs delay", top_k=1)[0]
    assert top_doc["doc_id"] == "CUST"
    assert 0.0 <= score <= 1.0001


def test_semantic_search_returns_k_ranked():
    vocab = ["customs", "weather", "strike", "delay", "port"]
    store = QdrantDocumentStore.in_memory(bag_of_words_embedder(vocab), vector_size=len(vocab))
    store.index([
        {"doc_id": "CUST", "text": "customs customs delay"},
        {"doc_id": "WX", "text": "weather port"},
        {"doc_id": "STRIKE", "text": "strike strike"},
    ])
    results = store.semantic_search("customs delay at the port", top_k=3)
    assert len(results) == 3
    scores = [s for _, s in results]
    assert scores == sorted(scores, reverse=True)  # descending similarity
