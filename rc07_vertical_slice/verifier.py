from __future__ import annotations

import re

from agent_contract import (
    AgentResponse,
    ClaimType,
    Outcome,
    Relevance,
    SupportStatus,
    Verification,
    VerificationCheck,
)


# Match a delay figure in several phrasings so the verifier and any evidence-fact
# wording agree: "8 days late", "8 days of delay", "delay 8 days", "delay of 8 days",
# "delay_days=8", "8-day delay".
_DELAY_RE = re.compile(
    r"\b(?:delay(?:_days)?\s*(?:of|=|:)?\s*(\d+(?:\.\d+)?)"
    r"|(\d+(?:\.\d+)?)\s*-?\s*days?\s+(?:late|of\s+delay|delay)"
    r"|(\d+(?:\.\d+)?)\s+days?\b)",
    re.IGNORECASE,
)


def _extract_delay_days(text: str) -> float | None:
    match = _DELAY_RE.search(text)
    if not match:
        return None
    for g in match.groups():
        if g is not None:
            return float(g)
    return None


_NUM_DAYS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*days?", re.IGNORECASE)


def _extract_all_delay_numbers(text: str) -> list[float]:
    """All 'N days' figures in text, as floats, in order. Used by the comparative check."""
    return [float(m) for m in _NUM_DAYS_RE.findall(text)]


def _status(value: bool) -> str:
    return "PASS" if value else "FAIL"


def verify_response(response: AgentResponse) -> AgentResponse:
    evidence_by_id = {e.evidence_id: e for e in response.evidence}

    # A verify_evidence trace entry must never count as evidence-producing itself.
    # Otherwise the verifier could "launder" an evidence ID by adding it to its own
    # output_refs after the fact. Only successful non-verification tools can produce
    # evidence.
    trace_output_refs = {
        ref
        for entry in response.tool_trace
        if entry.tool != "verify_evidence" and entry.status == "SUCCESS"
        for ref in entry.output_refs
    }

    checks: list[VerificationCheck] = []

    # I1/I2: every final claim must bind to real evidence and to evidence actually
    # produced by a successful non-verification tool.
    for claim in response.claims:
        missing = [eid for eid in claim.evidence_ids if eid not in evidence_by_id]
        checks.append(
            VerificationCheck(
                check_id=f"CHK-TRACE-{claim.claim_id}",
                type="CLAIM_EVIDENCE_BINDING",
                claim_id=claim.claim_id,
                status=_status(not missing),
                detail=None if not missing else f"Missing evidence IDs: {missing}",
            )
        )

        if claim.support_status == SupportStatus.UNSUPPORTED:
            checks.append(
                VerificationCheck(
                    check_id=f"CHK-UNSUPPORTED-{claim.claim_id}",
                    type="UNSUPPORTED_CLAIM_EXCLUSION",
                    claim_id=claim.claim_id,
                    status=_status(claim.text not in response.answer),
                    detail="Unsupported claims must not appear in the answer.",
                )
            )

        orphan_evidence = [eid for eid in claim.evidence_ids if eid not in trace_output_refs]
        checks.append(
            VerificationCheck(
                check_id=f"CHK-PRODUCED-{claim.claim_id}",
                type="EVIDENCE_PRODUCED_BY_TOOL",
                claim_id=claim.claim_id,
                status=_status(not orphan_evidence),
                detail=None
                if not orphan_evidence
                else f"Evidence not produced by a successful non-verification tool: {orphan_evidence}",
            )
        )

    # V1: numeric claims backed by SQL must match the numeric fact in the SQL evidence.
    # For RC-07 the relevant quantity is delay in days. Failing closed is preferable to
    # silently accepting an unparseable number.
    for claim in response.claims:
        if claim.claim_type != ClaimType.NUMERIC:
            continue

        sql_evidence = [
            evidence_by_id[eid]
            for eid in claim.evidence_ids
            if eid in evidence_by_id and evidence_by_id[eid].source_type.value == "SQL"
        ]
        if not sql_evidence:
            continue

        claim_delay = _extract_delay_days(claim.text)
        evidence_delays = {
            delay
            for evidence in sql_evidence
            if (delay := _extract_delay_days(evidence.fact)) is not None
        }

        numeric_ok = claim_delay is not None and len(evidence_delays) == 1 and claim_delay in evidence_delays
        detail = (
            f"Claim delay={claim_delay:g}; SQL evidence delay={next(iter(evidence_delays)):g}."
            if claim_delay is not None and len(evidence_delays) == 1
            else "Could not deterministically extract one delay value from the claim and SQL evidence."
        )
        checks.append(
            VerificationCheck(
                check_id=f"CHK-NUMERIC-{claim.claim_id}",
                type="NUMERIC_CLAIM_MATCHES_SQL",
                claim_id=claim.claim_id,
                status=_status(numeric_ok),
                detail=detail,
            )
        )

    # V1b: a COMPARATIVE claim backed by SQL must have BOTH compared figures present in
    # the SQL evidence, and must state a real gap (the two figures differ). This is how
    # RC-02's de-confounded "supplier vs peers on clean routes" claim is verified without
    # overclaiming causation.
    for claim in response.claims:
        if claim.claim_type != ClaimType.COMPARATIVE:
            continue
        sql_evidence = [
            evidence_by_id[eid]
            for eid in claim.evidence_ids
            if eid in evidence_by_id and evidence_by_id[eid].source_type.value == "SQL"
        ]
        if not sql_evidence:
            continue
        claim_nums = _extract_all_delay_numbers(claim.text)
        evidence_nums = set()
        for ev in sql_evidence:
            evidence_nums.update(_extract_all_delay_numbers(ev.fact))

        # The two COMPARED base figures must each be grounded in SQL evidence. A third
        # number may appear in the claim as the DERIVED gap (difference of the two); it
        # need not be in evidence, but if present it must be arithmetically correct.
        grounded = [cn for cn in claim_nums if any(abs(cn - en) < 0.01 for en in evidence_nums)]
        ungrounded = [cn for cn in claim_nums if cn not in grounded]

        base_ok = len(grounded) >= 2
        has_gap = base_ok and (max(grounded) - min(grounded) > 0.01)
        gap_val = round(max(grounded) - min(grounded), 2) if base_ok else None
        derived_ok = all(abs(u - gap_val) < 0.01 for u in ungrounded) if base_ok else False

        comparative_ok = base_ok and has_gap and derived_ok
        detail = (
            f"Grounded figures={sorted(grounded)}; derived/ungrounded={sorted(ungrounded)}; "
            f"expected gap={gap_val}; SQL evidence figures={sorted(evidence_nums)}."
            if claim_nums else
            "Could not extract two comparable figures from the claim."
        )
        checks.append(
            VerificationCheck(
                check_id=f"CHK-COMPARATIVE-{claim.claim_id}",
                type="COMPARATIVE_CLAIM_MATCHES_SQL",
                claim_id=claim.claim_id,
                status=_status(comparative_ok),
                detail=detail,
            )
        )

    # V2: a causal claim marked SUPPORTED requires direct documentary evidence.
    # Contextual evidence can inform an investigation, but cannot by itself establish
    # that a specific shipment was caused by a particular event.
    causal_claims = [
        c for c in response.claims
        if c.claim_type == ClaimType.CAUSAL and c.support_status == SupportStatus.SUPPORTED
    ]
    for claim in causal_claims:
        bound_evidence = [evidence_by_id[eid] for eid in claim.evidence_ids if eid in evidence_by_id]
        direct_docs = [
            e for e in bound_evidence
            if e.source_type.value == "DOCUMENT" and e.relevance == Relevance.DIRECT
        ]
        non_direct_docs = [
            e for e in bound_evidence
            if e.source_type.value == "DOCUMENT" and e.relevance != Relevance.DIRECT
        ]
        causal_ok = bool(direct_docs) and not any(
            e.relevance == Relevance.CONTRADICTORY for e in non_direct_docs
        )
        checks.append(
            VerificationCheck(
                check_id=f"CHK-CAUSAL-{claim.claim_id}",
                type="CAUSAL_REQUIRES_DIRECT_DOCUMENTARY_EVIDENCE",
                claim_id=claim.claim_id,
                status=_status(causal_ok),
                detail=(
                    "At least one DIRECT document supports the causal claim."
                    if causal_ok
                    else "A SUPPORTED causal claim needs DIRECT document evidence; CONTEXTUAL evidence is insufficient."
                ),
            )
        )

    # A legitimate PARTIALLY_SUPPORTED response is different from a response that was
    # downgraded because verification caught a defect: it should already contain at
    # least one PARTIAL claim and have no failed checks.
    failed_checks = [check for check in checks if check.status == "FAIL"]
    if response.outcome == Outcome.PARTIALLY_SUPPORTED:
        partial_claims = [c for c in response.claims if c.support_status == SupportStatus.PARTIAL]
        has_partial_claim = bool(partial_claims)
        checks.append(
            VerificationCheck(
                check_id="CHK-PARTIAL-SEMANTICS",
                type="LEGITIMATE_PARTIAL_OUTCOME",
                status=_status(has_partial_claim),
                detail=(
                    "Partial outcome is explicitly represented by one or more PARTIAL claims."
                    if has_partial_claim
                    else "PARTIALLY_SUPPORTED requires at least one claim with support_status=PARTIAL."
                ),
            )
        )
        failed_checks = [check for check in checks if check.status == "FAIL"]

    verification_status = "FAILED" if failed_checks else "PASSED"
    response.verification = Verification(
        status=verification_status,
        checks=checks,
    )

    # Outcome policy:
    # - already-valid PARTIAL stays PARTIAL;
    # - a supported response with a failed ordinary check is downgraded to PARTIAL;
    # - a SUPPORTED causal claim with no DIRECT evidence is stronger than a generic
    #   verification failure: the correct answer state is INSUFFICIENT_EVIDENCE.
    causal_direct_fail = any(
        check.type == "CAUSAL_REQUIRES_DIRECT_DOCUMENTARY_EVIDENCE" and check.status == "FAIL"
        for check in checks
    )
    if causal_direct_fail:
        response.outcome = Outcome.INSUFFICIENT_EVIDENCE
    elif failed_checks and response.outcome == Outcome.SUPPORTED:
        response.outcome = Outcome.PARTIALLY_SUPPORTED

    return response
