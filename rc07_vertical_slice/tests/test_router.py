"""
Router classification tests (deterministic, no DB/LLM — mock llm_call).
Pins: correct routing, garbage-LLM fallback, and the pattern-override guard that stops
a weak model wrongly refusing a clear entity question.
"""
import router


def _good(system, user):
    if "SH-" in user:
        return '{"type":"shipment"}'
    if "S07" in user or "supplier" in user:
        return '{"type":"supplier"}'
    return '{"type":"out_of_scope"}'


def _garbage(system, user):
    return "uhh maybe a shipment, no json here"


def _wrong_oos(system, user):
    return '{"type":"out_of_scope"}'


def test_good_llm_routes_correctly():
    assert router.classify(_good, "What happened to shipment SH-4921?") == "shipment"
    assert router.classify(_good, "Why is supplier S07 chronically late?") == "supplier"
    assert router.classify(_good, "What is the capital of France?") == "out_of_scope"


def test_garbage_llm_falls_back_to_pattern():
    assert router.classify(_garbage, "What happened to shipment SH-4921?") == "shipment"
    assert router.classify(_garbage, "Why is supplier S07 late?") == "supplier"
    assert router.classify(_garbage, "How do I bake bread?") == "out_of_scope"


def test_clear_entity_overrides_wrong_llm_refusal():
    # LLM wrongly says out_of_scope, but SH- pattern must win
    assert router.classify(_wrong_oos, "What happened to shipment SH-4921?") == "shipment"
    assert router.classify(_wrong_oos, "Why is supplier S07 late?") == "supplier"


def test_out_of_scope_question_refuses():
    resp = router.investigate(_good, "fake://db", "fixtures", "What is the capital of France?")
    from agent_contract import Outcome
    assert resp.outcome == Outcome.INSUFFICIENT_EVIDENCE
    assert resp.claims == []
