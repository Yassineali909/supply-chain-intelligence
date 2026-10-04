"""
Router integration tests for the analytical route (step 5). Confirms the precedence is
correct AND that analytical does not steal any of the 7 scenarios. Hermetic: the LLM is a
mock that returns out_of_scope, so the DETERMINISTIC routing is what's exercised.
"""
import pytest

import router
from router import classify, investigate


def out_of_scope_llm(system, user):
    # Forces the deterministic path: for scenario questions classify falls back to `det`.
    return '{"type": "out_of_scope"}'


@pytest.mark.parametrize("q", [
    "how many shipments used CR3?",
    "count of disputed invoices",
    "what is the average delay in March?",
    "how many suppliers do we have?",
])
def test_classify_routes_analytical(q):
    assert classify(out_of_scope_llm, q) == "analytical"


@pytest.mark.parametrize("q,expected", [
    ("why is supplier S07 chronically late?", "supplier"),
    ("average delay for S07", "supplier"),             # entity-qualified aggregate -> scenario
    ("how many days late is S07 on average?", "supplier"),
    ("is carrier CR3 getting worse?", "carrier"),
    ("what happened to shipment SH-4921?", "shipment"),
    ("why are WH-2 deliveries slow?", "warehouse"),
    ("which supplier is the worst?", "supplier"),       # -> ranking inside the supplier branch
    ("which customers are affected by port congestion?", "impact"),
    ("why are shipments through PORT-GEN delayed in Q1?", "port"),
])
def test_classify_does_not_steal_scenarios(q, expected):
    assert classify(out_of_scope_llm, q) == expected


def test_investigate_dispatches_analytical(monkeypatch):
    called = {}

    def stub(llm_call, database_url, question):
        called["q"] = question
        return "SENTINEL"

    monkeypatch.setattr(router, "investigate_analytical", stub)
    result = investigate(out_of_scope_llm, "db://x", "docs/", "how many shipments used CR3?")
    assert result == "SENTINEL"
    assert called["q"] == "how many shipments used CR3?"
