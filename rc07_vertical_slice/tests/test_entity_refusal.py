"""
Entity-validation refusal tests (regression for the held-out "Genoa port" bug).

A question routed to port/warehouse/carrier by KEYWORD but naming no valid entity code
must REFUSE (INSUFFICIENT_EVIDENCE), not silently default to the planted entity
(PORT-GEN/WH-2/CR3). Answering about the wrong entity is confidently-wrong output.

These tests use classify() + the refusal helper directly (no live DB): the refusal
happens in the router BEFORE any investigation import, so it is hermetic.
"""
import router
from agent_contract import Outcome


def _run(question):
    # LLM forced to out_of_scope so routing rides the deterministic layer; the no-code
    # refusal happens in dispatch regardless of which investigation it would have hit.
    dummy = lambda s, u: '{"type":"out_of_scope"}'
    return router.investigate(dummy, "fake://db", "/no/docs", question)


def test_unknown_port_refuses():
    r = _run("Tell me about congestion at the Genoa port.")
    assert r.outcome == Outcome.INSUFFICIENT_EVIDENCE
    assert r.claims == []
    assert "port" in r.answer.lower()   # names what it couldn't identify


def test_port_keyword_no_code_refuses():
    r = _run("Why is the port congested?")
    assert r.outcome == Outcome.INSUFFICIENT_EVIDENCE
    assert r.claims == []


def test_warehouse_keyword_no_code_refuses():
    r = _run("Why are deliveries slow during the peak?")
    assert r.outcome == Outcome.INSUFFICIENT_EVIDENCE
    assert r.claims == []


def test_carrier_keyword_no_code_refuses():
    r = _run("Is the carrier getting worse?")
    assert r.outcome == Outcome.INSUFFICIENT_EVIDENCE
    assert r.claims == []


def test_refusal_helper_message_names_entity_and_example():
    # the helper should tell the user what to name
    resp = router._refusal_no_entity("whatever", "port", "PORT-GEN")
    assert resp.outcome == Outcome.INSUFFICIENT_EVIDENCE
    assert "port" in resp.answer.lower()
    assert "PORT-GEN" in resp.answer
