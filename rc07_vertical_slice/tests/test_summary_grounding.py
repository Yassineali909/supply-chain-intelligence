"""Regression lock for the doc_search summary grounding gate (build #1).

Pins the design the live B21 calibration settled on:
  - G1-G3 are the SOUND, blocking gate (verbatim citation / number / code).
  - Fabricated specifics (invented citation / number / code) MUST reject.
  - A verbose-but-FAITHFUL summary MUST pass (the regression NG was causing).
  - NG novelty is advisory only and never changes `ok` (no threshold to guess).
  - R5 (causal) and R6 (novel prose) pass the lexical gate BY DESIGN -- documented
    residuals handled by claim-typing / honest labeling, asserted here so a future
    change that silently starts/stops catching them is caught.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from summary_grounding import verify_summary_grounding, _content_tokens

R = {
    "doc_0012": "Shipment SH-4921 was held at PORT-GEN for 6 days awaiting a customs inspection of the manifest.",
    "doc_0048": "Carrier CR3 handled the reroute after the customs hold cleared; no damage was reported.",
    "doc_0099": "The customs documentation was incomplete, which triggered the inspection.",
}

def _ok(s):
    ok, _ = verify_summary_grounding(s, R); return ok

def _reasons(s):
    _, v = verify_summary_grounding(s, R)
    return [r for vd in v for r in vd.reasons]


def test_faithful_summary_passes():
    assert _ok("These documents describe a customs hold on shipment SH-4921 at PORT-GEN [doc_0012][doc_0099].")

def test_invented_citation_rejects():
    s = "These documents describe a customs hold [doc_7777]."
    assert not _ok(s)
    assert any("G1" in r for r in _reasons(s))

def test_no_citation_rejects():
    assert not _ok("These documents describe a customs hold.")

def test_invented_number_rejects():
    s = "The shipment was held for 14 days [doc_0012]."
    assert not _ok(s)
    assert any("G2" in r and "14" in r for r in _reasons(s))

def test_invented_code_rejects():
    s = "Carrier CR5 handled the reroute [doc_0048]."
    assert not _ok(s)
    assert any("G3" in r for r in _reasons(s))

def test_grounded_number_passes():
    # 6 appears verbatim in doc_0012 -> G2 must NOT fire
    assert _ok("Shipment SH-4921 was held for 6 days [doc_0012].")

def test_verbose_faithful_passes_despite_high_novelty():
    # The exact regression NG caused: faithful framing words, zero fabricated specifics.
    s = "These records describe a recurring problem across multiple incidents over a short period [doc_0099]."
    assert _ok(s)
    _, v = verify_summary_grounding(s, R)
    assert any(vd.novel_terms for vd in v)   # novelty IS high...
    assert all(vd.grounded for vd in v)      # ...but it does not block

def test_ng_is_nonblocking_signal_only():
    # Novel terms are surfaced on the verdict but never flip `ok`.
    s = "These documents concern a highly unusual anomalous irregularity [doc_0099]."
    ok, v = verify_summary_grounding(s, R)
    assert ok is True
    assert any(vd.novel_terms for vd in v)

def test_novelty_slack_does_not_gate():
    # Same input, wildly different slack -> identical verdict (slack is advisory).
    s = "These records describe a recurring problem over a short period [doc_0099]."
    a, _ = verify_summary_grounding(s, R, novelty_slack=0)
    b, _ = verify_summary_grounding(s, R, novelty_slack=99)
    assert a == b is True

def test_causal_residual_R5_passes_lexical_gate():
    # Documented: the lexical gate does NOT catch causal over-assertion; claim-typing does.
    assert _ok("The customs hold was caused by incomplete documentation [doc_0099].") is True

def test_prose_residual_R6_passes_lexical_gate():
    # Documented honest ceiling: non-causal novel prose with no fabricated specific.
    # (Ships as unverified synthesis over displayed docs, not as a verified claim.)
    assert _ok("There was significant disruption at the facility [doc_0099].") is True

def test_mutation_g2_extractor_ignores_code_digits():
    # A digit glued to an entity code (SH-4921) must NOT be scanned as a bare number.
    assert _ok("Shipment SH-4921 is referenced [doc_0012].")
