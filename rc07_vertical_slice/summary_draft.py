"""
summary_draft.py - the grounded-summary drafter for the `doc_search` route (build #1).

D22 deferred LLM synthesis in doc_search because it needs its OWN hallucination verifier.
This module is the synthesis step, gated by exactly that verifier: the LLM DRAFTS a short
summary of the retrieved documents, and its output is NEVER trusted - every draft is run
through summary_grounding.verify_summary_grounding(), and a draft with any ungrounded
sentence is refused (after one bounded re-prompt that tells the model which sentences failed
and why). Nothing ungrounded is ever shown; on failure the caller falls back to the D22
retrieve-and-report answer.

Mirrors analytical_draft.py: injected llm_call (testable with a mock, no hard Ollama dep),
prompt-constrained AND verifier-gated, one bounded retry. Claim typing is NOT decided here -
a causal summary sentence is still caught downstream by the contract's CAUSAL check (D18).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from summary_grounding import verify_summary_grounding, _CITE_RE

LLMCall = Callable[[str, str], str]


@dataclass(frozen=True)
class SummaryDraftResult:
    ok: bool
    summary: Optional[str] = None
    reason: Optional[str] = None
    cited_doc_ids: tuple[str, ...] = ()
    verdicts: tuple[tuple, ...] = ()
    drafts: tuple[str, ...] = ()
    attempts: int = 0


_SYSTEM_TEMPLATE = """You summarize what a set of retrieved documents say about a question.

STRICT RULES:
- Use ONLY the facts stated in the documents provided. Add nothing that is not in them.
- Do NOT infer, guess, or assert WHY something happened. If the documents do not state a
  cause, do not state one. Report only what the documents say.
- Write a QUALITATIVE summary: report what the documents are ABOUT and the themes they share.
  Do NOT enumerate or list specific shipment codes, incident ids, numeric delay values, or
  dates - if you cannot copy a specific value verbatim from a document, do not state it.
- Every SENTENCE must itself end with its citation(s) in square brackets, e.g. [doc_0012] or
  [doc_0012][doc_0099]. Never put citations on a separate line or group them at the end.
- Never write a document id that is not in the provided list.
- At most {max_sentences} sentences. Output ONLY the summary - no preamble, no markdown.
- If the documents do not actually address the question, output exactly: CANNOT_SUMMARIZE

GOOD (qualitative, cited per sentence):
  These documents describe customs holds affecting several shipments [doc_0012][doc_0099].
BAD (enumerates specifics - invites fabrication):
  Delays were 3, 4, and 7 days for SH-4415, SH-4962, and SH-4439 [doc_0012]."""

_USER_TEMPLATE = """QUESTION: {question}

DOCUMENTS (cite using these exact ids):
{docs}"""

_RETRY_SUFFIX = """

Your previous summary was REJECTED - these sentences were not grounded in the documents:
{reasons}
Rewrite so EVERY sentence is supported by the listed documents and cites them by id. Summary only."""

_CANNOT_SUMMARIZE = "CANNOT_SUMMARIZE"


def _render_docs(retrieved: dict) -> str:
    return "\n".join(f"[{doc_id}] {text}" for doc_id, text in retrieved.items())


def _build_system(max_sentences: int) -> str:
    return _SYSTEM_TEMPLATE.format(max_sentences=max_sentences)


_FENCE_RE = re.compile(r"```(?:\w+)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_LABEL_RE = re.compile(r"^\s*(summary|answer)\s*:\s*", re.IGNORECASE)


def extract_summary(text: str) -> str:
    if text is None:
        return ""
    t = text.strip()
    m = _FENCE_RE.search(t)
    if m:
        t = m.group(1).strip()
    t = _LABEL_RE.sub("", t).strip()
    return t.strip().strip('"').strip()


def _cited_ids(summary: str) -> set:
    return set(_CITE_RE.findall(summary))


def _format_reasons(verdicts) -> str:
    return "\n".join(
        f'    - "{v.sentence}": ' + "; ".join(v.reasons)
        for v in verdicts if not v.grounded)


def _freeze(verdicts) -> tuple:
    return tuple((v.sentence, v.grounded, tuple(v.reasons)) for v in verdicts)


def draft_and_verify_summary(
    llm_call: LLMCall,
    question: str,
    retrieved: dict,
    *,
    max_sentences: int = 4,
    novelty_slack: int = 0,
    max_attempts: int = 2,
) -> SummaryDraftResult:
    """novelty_slack is the B21-class threshold - MUST be measured on real drafts before trust.
    Default 0 (strict) is a placeholder, not a calibrated value."""
    system = _build_system(max_sentences)
    docs_block = _render_docs(retrieved)
    base_user = _USER_TEMPLATE.format(question=question, docs=docs_block)

    drafts: list[str] = []
    verdicts = []
    last_reasons = ""

    for attempt in range(1, max_attempts + 1):
        user = base_user if attempt == 1 else base_user + _RETRY_SUFFIX.format(reasons=last_reasons)
        raw = llm_call(system, user)
        drafts.append(raw if raw is not None else "")

        candidate = extract_summary(raw)

        if candidate.strip().upper().startswith(_CANNOT_SUMMARIZE):
            return SummaryDraftResult(
                ok=False,
                reason="the model declined to summarize (documents do not address the question)",
                drafts=tuple(drafts), attempts=attempt)

        ok, verdicts = verify_summary_grounding(candidate, retrieved, novelty_slack=novelty_slack)
        if ok:
            return SummaryDraftResult(
                ok=True, summary=candidate,
                cited_doc_ids=tuple(sorted(_cited_ids(candidate))),
                verdicts=_freeze(verdicts), drafts=tuple(drafts), attempts=attempt)

        last_reasons = _format_reasons(verdicts)

    return SummaryDraftResult(
        ok=False,
        reason=f"summary failed grounding after {max_attempts} attempt(s)",
        verdicts=_freeze(verdicts), drafts=tuple(drafts), attempts=max_attempts)


if __name__ == "__main__":
    RETRIEVED = {
        "doc_0012": "Shipment SH-4921 was held at PORT-GEN for 6 days awaiting a customs inspection of the manifest.",
        "doc_0048": "Carrier CR3 handled the reroute after the customs hold cleared; no damage was reported.",
        "doc_0099": "The customs documentation was incomplete, which triggered the inspection.",
    }
    GOOD = "These documents describe a customs hold affecting shipment SH-4921 at PORT-GEN [doc_0012]."
    BAD  = "Shipment SH-4921 was held at PORT-GEN for 14 days [doc_0012]."   # fabricated number -> G2

    def mock(*responses):
        it = iter(responses)
        return lambda system, user: next(it)

    def show(name, r):
        print(f"\n[{name}]  ok={r.ok}  attempts={r.attempts}")
        if r.ok:
            print(f"    summary: {r.summary}")
            print(f"    cited:   {list(r.cited_doc_ids)}")
        else:
            print(f"    refused: {r.reason}")
            for sent, grounded, reasons in r.verdicts:
                if not grounded:
                    print(f"      X {sent}  -> {'; '.join(reasons)}")

    print("=" * 74)
    print("A - clean draft, grounded on attempt 1")
    show("A happy-path", draft_and_verify_summary(mock(GOOD), "customs holds?", RETRIEVED))
    print("\n" + "=" * 74)
    print("B - hallucinated draft, recovers on retry (reason fed back)")
    show("B retry-recovers", draft_and_verify_summary(mock(BAD, GOOD), "customs holds?", RETRIEVED))
    print("\n" + "=" * 74)
    print("C - ungrounded both times -> refuse -> caller falls back to D22 report-only")
    show("C hard-refuse", draft_and_verify_summary(mock(BAD, BAD), "customs holds?", RETRIEVED))
    print("=" * 74)
