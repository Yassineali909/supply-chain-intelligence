import main


def test_verify_tool_does_not_launder_evidence_refs():
    response = main.fixture_response()
    verify_entries = [t for t in response.tool_trace if t.tool == "verify_evidence"]
    assert len(verify_entries) == 1
    assert verify_entries[0].output_refs == []


def test_fixture_numeric_claim_is_verified_against_sql_fact():
    response = main.fixture_response()
    check = next(c for c in response.verification.checks if c.type == "NUMERIC_CLAIM_MATCHES_SQL")
    assert check.status == "PASS"
    assert "8" in (check.detail or "")
