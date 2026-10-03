"""
RC-03 carrier-degradation tests. Mock the two carrier query tools (no live DB).
Pins: the investigation produces a LEGITIMATELY PARTIAL TREND verdict (outcome
PARTIALLY_SUPPORTED with a PARTIAL claim AND the LEGITIMATE_PARTIAL_OUTCOME check PASS —
not a downgrade); refuses when the trend isn't actually rising (honesty gate); and the
router routes a carrier question to 'carrier', not 'supplier'.
"""
import rc03
import router
from postgres_tool import SQLToolResult
from agent_contract import Outcome, ClaimType, SupportStatus


def _rising(db, carrier_code, **k):
    # CR3's live thirds: 2.06 -> 3.07 -> 4.54 (monotonic)
    return SQLToolResult("EVD-T1", "SQL-T1", [
        {"third": 1, "n": 174, "avg_delay_days": 2.06},
        {"third": 2, "n": 142, "avg_delay_days": 3.07},
        {"third": 3, "n": 157, "avg_delay_days": 4.54},
    ], {"tool_call_id": "TC-T1", "parameters": {"carrier_code": carrier_code}})


def _fleet_flat(db, carrier_code, **k):
    return SQLToolResult("EVD-T2", "SQL-T2", [
        {"third": 1, "n": 852, "avg_delay_days": 1.66},
        {"third": 2, "n": 799, "avg_delay_days": 1.20},
        {"third": 3, "n": 876, "avg_delay_days": 1.47},
    ], {"tool_call_id": "TC-T2", "parameters": {}})


def test_rc03_legitimate_partial_trend(monkeypatch):
    monkeypatch.setattr(rc03, "carrier_delay_by_thirds", _rising)
    monkeypatch.setattr(rc03, "carrier_thirds_fleet", _fleet_flat)
    resp = rc03.investigate_rc03("fake://db", "CR3")
    assert resp.outcome == Outcome.PARTIALLY_SUPPORTED
    assert resp.claims[0].claim_type == ClaimType.TREND
    assert resp.claims[0].support_status == SupportStatus.PARTIAL
    # the KEY assertion: PARTIAL is legitimate (set by intent), NOT a verification downgrade.
    # mirrors test_legitimate_partial_is_distinct_from_verification_downgrade.
    partial_check = next(c for c in resp.verification.checks if c.type == "LEGITIMATE_PARTIAL_OUTCOME")
    assert partial_check.status == "PASS"
    assert resp.verification.status == "PASSED"
    assert [t.tool for t in resp.tool_trace] == ["query_database", "query_database", "verify_evidence"]


def test_rc03_non_rising_carrier_refuses(monkeypatch):
    # honesty gate: a flat/improving carrier must NOT get a degradation claim
    def flat(db, carrier_code, **k):
        return SQLToolResult("EVD-T1", "SQL-T1", [
            {"third": 1, "n": 100, "avg_delay_days": 2.0},
            {"third": 2, "n": 100, "avg_delay_days": 2.0},
            {"third": 3, "n": 100, "avg_delay_days": 1.9},  # not rising
        ], {"tool_call_id": "TC-T1", "parameters": {}})
    monkeypatch.setattr(rc03, "carrier_delay_by_thirds", flat)
    monkeypatch.setattr(rc03, "carrier_thirds_fleet", _fleet_flat)
    resp = rc03.investigate_rc03("fake://db", "CR9")
    assert resp.outcome == Outcome.INSUFFICIENT_EVIDENCE
    assert resp.claims == []


def test_rc03_missing_thirds_yields_insufficient(monkeypatch):
    monkeypatch.setattr(rc03, "carrier_delay_by_thirds",
        lambda db, carrier_code, **k: SQLToolResult("EVD-T1", "SQL-T1", [], {"tool_call_id": "TC-T1", "parameters": {}}))
    monkeypatch.setattr(rc03, "carrier_thirds_fleet", _fleet_flat)
    resp = rc03.investigate_rc03("fake://db", "CR3")
    assert resp.outcome == Outcome.INSUFFICIENT_EVIDENCE


def test_router_routes_carrier_questions():
    dummy = lambda s, u: '{"type":"out_of_scope"}'
    # carrier question -> carrier (RC-03), NOT supplier — pins the B11-style disambiguation
    assert router.classify(dummy, "Is carrier CR3 getting worse over time?") == "carrier"
    # a supplier question must still route to supplier (the carrier branch didn't steal it)
    assert router.classify(dummy, "Why is supplier S07 chronically late?") == "supplier"