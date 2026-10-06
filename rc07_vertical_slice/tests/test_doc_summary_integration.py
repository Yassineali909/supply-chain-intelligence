"""Integration lock for the doc_search grounded-summary wiring (build #1, behind
USE_DOC_SUMMARY). Hermetic: a fake store + mock llm_call, no Ollama/Qdrant/Postgres.

Pins the three wiring contracts:
  - summarize on + grounded draft -> summary attached (answer led by the label) + trace grounded
  - summarize on + fabricating draft -> summary SUPPRESSED, pure D22 answer stands, trace suppressed
  - summarize off -> no summary, no TC-SUMMARY trace (default path untouched)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from semantic import investigate_doc_search

DOCS = [
    ({"doc_id": "DOC-001", "text": "Shipment SH-4921 was held at PORT-GEN for 6 days for a customs inspection."}, 0.71),
    ({"doc_id": "DOC-002", "text": "The customs documentation was incomplete, which triggered the inspection."}, 0.69),
]

class FakeStore:
    def semantic_search(self, question, top_k=5):
        return DOCS

GROUNDED = "These documents describe a customs hold on shipment SH-4921 at PORT-GEN [DOC-001][DOC-002]."
FABRICATED = "Shipment SH-4921 was held for 14 days due to a labor strike [DOC-001]."   # 14 absent -> G2

def mock(resp):
    return lambda system, user: resp


def test_summary_on_grounded_attaches():
    r = investigate_doc_search("customs holds?", store=FakeStore(),
                               summarize=True, llm_call=mock(GROUNDED))
    assert r.answer.startswith("Summary (unverified synthesis")
    tr = [t.input for t in r.tool_trace if t.tool_call_id == "TC-SUMMARY"]
    assert tr and tr[0]["status"] == "grounded"
    # the backbone D22 report is still present after the summary
    assert "relevant to your query" in r.answer

def test_summary_on_fabrication_suppressed_falls_back():
    r = investigate_doc_search("customs holds?", store=FakeStore(),
                               summarize=True, llm_call=mock(FABRICATED))
    assert not r.answer.startswith("Summary (unverified synthesis")   # suppressed
    assert "relevant to your query" in r.answer                       # pure D22 stands
    tr = [t.input for t in r.tool_trace if t.tool_call_id == "TC-SUMMARY"]
    assert tr and tr[0]["status"] == "suppressed"

def test_summary_off_is_untouched():
    r = investigate_doc_search("customs holds?", store=FakeStore(),
                               summarize=False, llm_call=mock(GROUNDED))
    assert not r.answer.startswith("Summary (unverified synthesis")
    assert [t for t in r.tool_trace if t.tool_call_id == "TC-SUMMARY"] == []

def test_summary_on_but_no_llm_is_safe():
    # summarize requested but no llm_call provided -> no summary, no crash
    r = investigate_doc_search("customs holds?", store=FakeStore(),
                               summarize=True, llm_call=None)
    assert not r.answer.startswith("Summary (unverified synthesis")

def test_outcome_unchanged_by_summary():
    # the summary must never alter the verified outcome (honesty boundary)
    base = investigate_doc_search("customs holds?", store=FakeStore(), summarize=False)
    summ = investigate_doc_search("customs holds?", store=FakeStore(),
                                  summarize=True, llm_call=mock(GROUNDED))
    assert base.outcome == summ.outcome
