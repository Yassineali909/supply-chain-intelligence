"""
patch_verifier.py — add the AGGREGATE claim type and its verifier check, safely.

Same scripted-patch discipline as patch_router.py (B10/B12/B16): each anchor must match
EXACTLY ONCE and its replacement must NOT already be present; all edits staged in memory;
each file written only if its edits all pass. Idempotent.

Edits:
  agent_contract.py : add ClaimType.AGGREGATE (additive enum member).
  verifier.py       : add the standalone-value extractor + the AGGREGATE_CLAIM_MATCHES_SQL
                      check loop. Purely additive — the loop runs only for AGGREGATE claims,
                      which no existing claim uses, so the 47 existing tests are unaffected.
"""
import sys

EDITS = {
    "agent_contract.py": [
        (
            '    CAUSAL = "CAUSAL"\n'
            '    COMPARATIVE = "COMPARATIVE"',

            '    CAUSAL = "CAUSAL"\n'
            '    COMPARATIVE = "COMPARATIVE"\n'
            '    AGGREGATE = "AGGREGATE"  # a value read directly from an aggregate SQL result (text-to-SQL)',
        ),
    ],
    "verifier.py": [
        # (a) the standalone-value extractor, after the delay-number helper.
        (
            'def _extract_all_delay_numbers(text: str) -> list[float]:\n'
            '    """All \'N days\' figures in text, as floats, in order. Used by the comparative check."""\n'
            '    return [float(m) for m in _NUM_DAYS_RE.findall(text)]',

            'def _extract_all_delay_numbers(text: str) -> list[float]:\n'
            '    """All \'N days\' figures in text, as floats, in order. Used by the comparative check."""\n'
            '    return [float(m) for m in _NUM_DAYS_RE.findall(text)]\n'
            '\n'
            '\n'
            '# A STANDALONE number: not glued to letters, a dot, or a hyphen on either side. This\n'
            '# deliberately ignores the digits inside entity codes (CR3, S07, WH-2, PORT-GEN, Q1,\n'
            '# SH-4921) so the AGGREGATE check reads only the result value, never a code\'s digits.\n'
            '_VALUE_RE = re.compile(r"(?<![\\w.\\-])(\\d+(?:\\.\\d+)?)(?!\\d)")\n'
            '\n'
            '\n'
            'def _extract_values(text: str) -> list[float]:\n'
            '    """All standalone numeric values in text (entity-code digits excluded)."""\n'
            '    return [float(m) for m in _VALUE_RE.findall(text)]\n'
            '\n'
            '\n'
            'def _extract_single_value(text: str) -> float | None:\n'
            '    """The one standalone value in text, or None if there isn\'t exactly one (fail closed)."""\n'
            '    vals = _extract_values(text)\n'
            '    return vals[0] if len(vals) == 1 else None',
        ),
        # (b) the AGGREGATE check loop, before the causal (V2) block.
        (
            '    # V2: a causal claim marked SUPPORTED requires direct documentary evidence.',

            '    # V1c: an AGGREGATE claim (text-to-SQL analytical result) must carry exactly the\n'
            '    # value its SQL evidence produced. This is a TRANSCRIPTION guard: it certifies the\n'
            '    # headline number in the claim equals the number the executed query returned, so a\n'
            '    # claim can never report a value the SQL did not. It does NOT certify that the SQL\n'
            '    # semantically answers the question — that residual risk (the hardest part of threat\n'
            '    # #6) is mitigated by surfacing the generated SQL in the evidence locator and the\n'
            '    # answer, for audit, not by this check. Day-valued analytical results still use the\n'
            '    # NUMERIC check above; AGGREGATE covers counts/sums and other non-day values that the\n'
            '    # days-only extractor cannot read (verified: a count marked NUMERIC fails closed).\n'
            '    for claim in response.claims:\n'
            '        if claim.claim_type != ClaimType.AGGREGATE:\n'
            '            continue\n'
            '        sql_evidence = [\n'
            '            evidence_by_id[eid]\n'
            '            for eid in claim.evidence_ids\n'
            '            if eid in evidence_by_id and evidence_by_id[eid].source_type.value == "SQL"\n'
            '        ]\n'
            '        if not sql_evidence:\n'
            '            continue\n'
            '        claim_val = _extract_single_value(claim.text)\n'
            '        evidence_vals = set()\n'
            '        for ev in sql_evidence:\n'
            '            evidence_vals.update(_extract_values(ev.fact))\n'
            '        aggregate_ok = claim_val is not None and any(\n'
            '            abs(claim_val - ev) < 1e-9 for ev in evidence_vals\n'
            '        )\n'
            '        detail = (\n'
            '            f"Claim value={claim_val:g}; SQL evidence values={sorted(evidence_vals)}."\n'
            '            if claim_val is not None\n'
            '            else "Could not deterministically extract one value from the claim."\n'
            '        )\n'
            '        checks.append(\n'
            '            VerificationCheck(\n'
            '                check_id=f"CHK-AGGREGATE-{claim.claim_id}",\n'
            '                type="AGGREGATE_CLAIM_MATCHES_SQL",\n'
            '                claim_id=claim.claim_id,\n'
            '                status=_status(aggregate_ok),\n'
            '                detail=detail,\n'
            '            )\n'
            '        )\n'
            '\n'
            '    # V2: a causal claim marked SUPPORTED requires direct documentary evidence.',
        ),
    ],
}


def patch_file(path, edits) -> int:
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    if all(new in src for _, new in edits):
        print(f"{path}: already patched — nothing to do.")
        return 0
    staged = src
    for anchor, new in edits:
        if new in staged:
            print(f"{path}: SKIP (already present)")
            continue
        count = staged.count(anchor)
        if count != 1:
            print(f"{path}: ABORT anchor matched {count} time(s), expected 1:\n  {anchor[:70]!r}")
            return 1
        staged = staged.replace(anchor, new, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(staged)
    print(f"{path}: patched.")
    return 0


def main() -> int:
    rc = 0
    for path, edits in EDITS.items():
        rc |= patch_file(path, edits)
    return rc


if __name__ == "__main__":
    sys.exit(main())
