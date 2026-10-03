"""
Supplier-ranking tests (the new 'which supplier is worst' capability).

Pins: the ranking produces a verified COMPARATIVE claim (worst vs next-worst gap) on the
de-confounded clean-route metric; refuses with fewer than two suppliers; and the router
FORK routes correctly — a ranking question (no S-code) -> ranking, a named supplier
(S-code) -> RC-02 even when 'worst' appears, and a bare supplier question -> refuse.
"""
import rc_ranking
import router
from postgres_tool import SQLToolResult
from agent_contract import AgentResponse, Outcome, ClaimType, Verification, Timing


def _ranking_rows(db, **k):
    # mirrors the live clean-route ranking: S07 worst at 5.27, S18 next at 2.08
    return SQLToolResult("EVD-RANK", "SQL-RANK", [
        {"supplier_code": "S07", "shipment_count": 183, "clean_avg_delay_days": 5.27},
        {"supplier_code": "S18", "shipment_count": 52,  "clean_avg_delay_days": 2.08},
        {"supplier_code": "S12", "shipment_count": 67,  "clean_avg_delay_days": 1.97},
    ], {"tool_call_id": "TC-RANK", "parameters": {"congested_port": "PORT-GEN", "top_n": 5}})


def _mark(tag):
    """A minimal SUPPORTED response whose answer is a routing marker."""
    return AgentResponse(run_id="R", question="q", outcome=Outcome.SUPPORTED, answer=tag,
                         claims=[], evidence=[], tool_trace=[],
                         verification=Verification(status="PASSED", checks=[]),
                         timing=Timing(total_ms=0, tool_ms=0))


def test_ranking_supported_comparative(monkeypatch):
    monkeypatch.setattr(rc_ranking, "supplier_ranking_clean", _ranking_rows)
    resp = rc_ranking.investigate_supplier_ranking("fake://db")
    assert resp.outcome == Outcome.SUPPORTED
    assert resp.verification.status == "PASSED"
    assert resp.claims[0].claim_type == ClaimType.COMPARATIVE
    # worst entity + the derived gap (5.27 - 2.08 = 3.19) must be in the claim
    assert "S07" in resp.claims[0].text
    assert "3.19" in resp.claims[0].text
    assert [t.tool for t in resp.tool_trace] == ["query_database", "verify_evidence"]


def test_ranking_insufficient_one_supplier(monkeypatch):
    def one(db, **k):
        return SQLToolResult("EVD-RANK", "SQL-RANK", [
            {"supplier_code": "S07", "shipment_count": 183, "clean_avg_delay_days": 5.27},
        ], {"tool_call_id": "TC-RANK", "parameters": {}})
    monkeypatch.setattr(rc_ranking, "supplier_ranking_clean", one)
    resp = rc_ranking.investigate_supplier_ranking("fake://db")
    assert resp.outcome == Outcome.INSUFFICIENT_EVIDENCE
    assert resp.claims == []


def test_router_fork_ranking_vs_named_vs_refuse(monkeypatch):
    """The supplier dispatch fork, hermetically (stub both investigations, no DB needed)."""
    monkeypatch.setattr(router, "classify", lambda llm, q: "supplier")
    monkeypatch.setattr("rc_ranking.investigate_supplier_ranking", lambda db, q, **k: _mark("RANK"))
    monkeypatch.setattr("rc02.investigate_rc02", lambda db, code, q, **k: _mark("RC02-" + code))

    dummy = lambda s, u: '{"type":"supplier"}'
    # ranking question, no code -> ranking
    assert router.investigate(dummy, "db", "docs", "Which supplier is the worst?").answer == "RANK"
    # named supplier with 'worst' -> RC-02 (S-code wins over ranking language)
    assert router.investigate(dummy, "db", "docs", "Is S07 the worst supplier?").answer == "RC02-S07"
    # bare supplier question, no code, no ranking kw -> refuse
    assert router.investigate(dummy, "db", "docs", "Tell me about supplier performance.").outcome == Outcome.INSUFFICIENT_EVIDENCE
