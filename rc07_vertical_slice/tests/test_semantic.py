"""
Tests for the semantic doc_search route. Hermetic: a FakeStore returns controllable
(doc, score) hits; the REAL verifier gates the result. No Qdrant/Ollama.
"""
import pytest

import semantic
from semantic import investigate_doc_search, is_doc_search_question
from agent_contract import ClaimType, Outcome, Relevance, SourceType


class FakeStore:
    def __init__(self, hits):
        self._hits = hits

    def semantic_search(self, query, top_k=5):
        return self._hits[:top_k]


def _doc(i, text="a customs hold delayed the shipment"):
    return {"doc_id": f"DOC-{i}", "text": text}


@pytest.mark.parametrize("q", [
    "What do our documents say about customs holds?",
    "find reports mentioning carrier delays",
    "what do the docs say about port congestion?",
    "search the incident reports about warehouse capacity",
])
def test_doc_search_questions_fire(q):
    assert is_doc_search_question(q) is True


@pytest.mark.parametrize("q", [
    "why is supplier S07 chronically late?",
    "how many shipments used CR3?",
    "what happened to shipment SH-6968?",
    "which supplier is the worst?",
    "average delay per carrier",
])
def test_non_doc_search_questions_do_not_fire(q):
    assert is_doc_search_question(q) is False


def test_relevant_hits_build_relationship_claim_and_verify():
    store = FakeStore([(_doc(0), 0.72), (_doc(1), 0.66), (_doc(2), 0.58)])
    resp = investigate_doc_search("what do our docs say about customs holds?", store=store)
    assert resp.outcome == Outcome.SUPPORTED
    assert resp.verification.status == "PASSED"
    assert len(resp.claims) == 1
    assert resp.claims[0].claim_type == ClaimType.RELATIONSHIP
    assert len(resp.evidence) == 3
    assert all(e.source_type == SourceType.DOCUMENT for e in resp.evidence)
    assert all(e.relevance == Relevance.CONTEXTUAL for e in resp.evidence)
    assert resp.claims[0].evidence_ids == [e.evidence_id for e in resp.evidence]


def test_below_floor_refuses_like_semantic_rc06():
    store = FakeStore([(_doc(0), 0.21), (_doc(1), 0.15)])
    resp = investigate_doc_search("something unrelated", store=store)
    assert resp.outcome == Outcome.INSUFFICIENT_EVIDENCE
    assert resp.claims == []
    assert "sufficiently relevant" in resp.answer


def test_mixed_scores_keeps_only_above_floor():
    store = FakeStore([(_doc(0), 0.80), (_doc(1), 0.50), (_doc(2), 0.65)])
    resp = investigate_doc_search("query", store=store, score_floor=0.6)
    assert resp.outcome == Outcome.SUPPORTED
    assert len(resp.evidence) == 2   # 0.80 and 0.65 kept; 0.50 dropped


def test_no_index_refuses_cleanly(monkeypatch):
    monkeypatch.setattr(semantic, "_default_store", lambda: None)
    resp = investigate_doc_search("what do our docs say about X?")
    assert resp.outcome == Outcome.INSUFFICIENT_EVIDENCE
    assert "requires the Qdrant index" in resp.answer


def test_floor_is_calibrated_to_corpus_distribution():
    # Measured on the real corpus: on-topic >=0.72, off-topic <=0.40. The floor must sit
    # in that gap so off-topic noise (the "delay notice" boilerplate ~0.40) is refused.
    from semantic import SCORE_FLOOR
    assert 0.40 < SCORE_FLOOR < 0.72
    store = FakeStore([(_doc(0), 0.44), (_doc(1), 0.40)])   # off-topic noise ceiling
    assert investigate_doc_search("quantum computing", store=store).outcome == Outcome.INSUFFICIENT_EVIDENCE
    store2 = FakeStore([(_doc(0), 0.72)])                   # real on-topic hit
    assert investigate_doc_search("customs holds", store=store2).outcome == Outcome.SUPPORTED


def test_router_routes_doc_search_without_stealing():
    from router import classify
    llm = lambda s, u: '{"type":"out_of_scope"}'
    assert classify(llm, "what do our documents say about customs holds?") == "doc_search"
    assert classify(llm, "find reports mentioning carrier delays") == "doc_search"
    assert classify(llm, "how many shipments used CR3?") == "analytical"
    assert classify(llm, "why is supplier S07 chronically late?") == "supplier"
    assert classify(llm, "what happened to shipment SH-6968?") == "shipment"
