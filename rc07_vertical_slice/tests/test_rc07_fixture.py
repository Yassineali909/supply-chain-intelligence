import main


def test_rc07_fixture_is_supported():
    response = main.fixture_response()
    assert response.outcome.value == "SUPPORTED"
    assert response.verification.status == "PASSED"
    assert [t.step for t in response.tool_trace] == [1, 2, 3]
    assert {"CLM-001", "CLM-002"} == {c.claim_id for c in response.claims}
    assert all(c.evidence_ids for c in response.claims)
