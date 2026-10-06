"""
summary_grounding.py -- grounding verifier for the doc_search LLM summary (build #1).

DESIGN (revised after live B21 calibration on the real corpus):

  The grounding GATE is G1-G3 ONLY -- the three VERBATIM-sound checks:
    G1 every sentence cites a retrieved doc_id (no invented/absent citation)
    G2 every number in a sentence appears verbatim in its cited doc(s)
    G3 every entity code in a sentence appears verbatim in its cited doc(s)
  These are SOUND: verbatim matching cannot be fooled, so they never false-"ground".
  On the real corpus they caught every fabricated specific the model produced.

  NG (novel-term count) is DEMOTED to a NON-BLOCKING advisory signal. Measurement
  proved it cannot be a gate: the novel-term count of a verbose-but-FAITHFUL summary
  ("a recurring problem over a short period") overlaps the count of a concise
  FABRICATION ("a labor strike at the port"); the populations are not separable by
  lexical novelty, so no threshold exists. NG is still computed and surfaced (for the
  trace / human audit) but it does NOT reject. There is no threshold to guess.

  What NG was a weak proxy for -- a summary asserting a NOVEL claim no document
  supports -- is handled where it is actually sound: a CAUSAL assertion becomes a
  CAUSAL claim and the contract's CAUSAL_REQUIRES_DIRECT_DOCUMENTARY_EVIDENCE check
  fails it (retrieved docs are CONTEXTUAL, not DIRECT). A NON-causal novel-prose
  assertion that invents no number/code is the HONEST CEILING of this lexical layer
  (R6 below): not deterministically catchable, so the summary is never presented as a
  verified claim -- it is unverified synthesis over the cited, DISPLAYED documents, and
  suppressed entirely if G1-G3 trip. Transcription-grounding, not semantic faithfulness
  -- the same honest limit as the AGGREGATE check (D18).
"""
import re
from dataclasses import dataclass, field

_NUM_RE  = re.compile(r'(?<![\w.\-])(\d+(?:\.\d+)?)(?!\d)')
_CODE_RE = re.compile(r'\b(?:SH-\d+|CR-?\d+|WH-?\d+|S\d{2,}|PORT-[A-Z]+|RT-\d+)\b', re.I)
_CITE_RE = re.compile(r'\[([A-Za-z][\w\-]*)\]')   # [DOC-002646] or [doc_0012]

_STOP = set("""a an the and or but of to in on for with at by from as is are was were be been being
it its their his her our your they we you i he she him them us me which who whom whose what when
where why how not no nor so than then there here into over under about above below between during
after before has have had do does did will would can could may might must shall should per each
any some all more most much many few also such only just very once that this these those""".split())


def _norm(tok):
    t = tok.lower()
    for suf in ("'s", "ing", "ed", "es", "s"):
        if len(t) > len(suf) + 2 and t.endswith(suf):
            return t[:-len(suf)]
    return t


def _content_tokens(text):
    out = set()
    for w in re.findall(r"[A-Za-z][A-Za-z\-']+", text):
        if w.lower() in _STOP or len(w) < 3:
            continue
        out.add(_norm(w))
    return out


def _codes(text):
    return {c.upper().replace('-', '') for c in _CODE_RE.findall(text)}


def _split_sentences(summary):
    return [p for p in re.split(r'(?<=[.!?])\s+', summary.strip()) if p.strip()]


@dataclass
class SentenceVerdict:
    sentence: str
    grounded: bool                                   # SOUND gates G1-G3 only
    reasons: list = field(default_factory=list)      # G1/G2/G3 failures (blocking)
    novel_terms: list = field(default_factory=list)  # NG advisory signal (non-blocking)


def verify_summary_grounding(summary, retrieved, *, novelty_slack=0):
    """Gate a summary on the SOUND checks G1-G3. Returns (ok, [SentenceVerdict]).

    ok iff every sentence passes G1-G3. The novel-term set (NG) is computed and stored
    on each verdict as an ADVISORY signal -- it never affects ok. `novelty_slack` is
    accepted for call-site compatibility and is advisory only (NG does not gate)."""
    retrieved_ids = set(retrieved)
    corpus_tokens = set()
    for t in retrieved.values():
        corpus_tokens |= _content_tokens(t)

    verdicts = []
    for s in _split_sentences(summary):
        reasons = []
        cites = set(_CITE_RE.findall(s))
        s_body = _CITE_RE.sub(' ', s)

        if not cites:
            reasons.append("G1 no citation")
        if cites - retrieved_ids:
            reasons.append(f"G1 cites non-retrieved {sorted(cites - retrieved_ids)}")

        cited_text = " ".join(retrieved[d] for d in (cites & retrieved_ids))
        cited_nums = set(_NUM_RE.findall(cited_text))
        cited_codes = _codes(cited_text)

        for n in _NUM_RE.findall(s_body):
            if n not in cited_nums:
                reasons.append(f"G2 number '{n}' absent from cited docs")
        for c in sorted(_codes(s_body) - cited_codes):
            reasons.append(f"G3 code '{c}' absent from cited docs")

        novel = sorted(_content_tokens(s_body) - corpus_tokens)   # advisory only
        verdicts.append(SentenceVerdict(s, not reasons, reasons, novel))

    return all(v.grounded for v in verdicts), verdicts


if __name__ == "__main__":
    R = {
        "doc_0012": "Shipment SH-4921 was held at PORT-GEN for 6 days awaiting a customs inspection of the manifest.",
        "doc_0048": "Carrier CR3 handled the reroute after the customs hold cleared; no damage was reported.",
        "doc_0099": "The customs documentation was incomplete, which triggered the inspection.",
    }
    GREEN = "These documents describe a customs hold on shipment SH-4921 at PORT-GEN, awaiting inspection [doc_0012][doc_0099]."
    R1 = "These documents describe a customs hold [doc_7777]."                      # invented citation
    R2 = "The shipment was held for 14 days [doc_0012]."                            # invented number
    R3 = "Carrier CR5 handled the reroute [doc_0048]."                              # invented code
    R4 = "These records describe a recurring problem across multiple incidents over a short period [doc_0099]."  # verbose-faithful
    R5 = "The customs hold was caused by a labor strike [doc_0099]."                # causal residual
    R6 = "There was a labor strike at the port [doc_0099]."                         # prose residual (ceiling)

    def ok(s):
        o, _ = verify_summary_grounding(s, R); return o
    def why(s):
        _, v = verify_summary_grounding(s, R)
        return "; ".join(r for vd in v for r in vd.reasons)
    def novel(s):
        _, v = verify_summary_grounding(s, R)
        return sorted({t for vd in v for t in vd.novel_terms})

    print("=" * 74)
    print("SOUND GATE (G1-G3) -- blocking")
    print("=" * 74)
    print(f"  GREEN faithful      -> {'GROUNDED' if ok(GREEN) else 'REJECT'}")
    print(f"  R1 invented cite    -> {'GROUNDED' if ok(R1) else 'REJECT'}   {why(R1)}")
    print(f"  R2 invented number  -> {'GROUNDED' if ok(R2) else 'REJECT'}   {why(R2)}")
    print(f"  R3 invented code    -> {'GROUNDED' if ok(R3) else 'REJECT'}   {why(R3)}")
    print(f"  R4 verbose-faithful -> {'GROUNDED' if ok(R4) else 'REJECT'}   (NG novelty high but non-blocking: {novel(R4)})")

    print("\n" + "=" * 74)
    print("DOCUMENTED RESIDUALS -- pass the lexical gate BY DESIGN; handled elsewhere")
    print("=" * 74)
    print(f"  R5 causal   -> {'passes lexical' if ok(R5) else 'rejected'}  novel={novel(R5)}  (caught by CAUSAL claim-typing)")
    print(f"  R6 prose    -> {'passes lexical' if ok(R6) else 'rejected'}  novel={novel(R6)}  (honest ceiling: unverified label + displayed docs)")

    green_ok = ok(GREEN)
    reds = (not ok(R1)) and (not ok(R2)) and (not ok(R3))
    r4_ok = ok(R4)
    print("\n" + "=" * 74)
    print(f"RESULT: green_grounded={green_ok}  specifics_rejected={reds}  verbose_faithful_passes={r4_ok}")
    print("PASS" if (green_ok and reds and r4_ok) else "FAIL -- investigate")
    print("=" * 74)
