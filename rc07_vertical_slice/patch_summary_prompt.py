"""patch_summary_prompt.py - harden the doc_search summary prompt after the live calibration
run showed llama3.2 enumerating (and fabricating) per-shipment specifics, and splitting the
citation onto its own line. Make the summary QUALITATIVE + force same-sentence citations.
Anchor-checked (each old block must match exactly once) + idempotent."""
import sys

P = "summary_draft.py"
src = open(P, encoding="utf-8").read()

MARKER = "report what the documents are ABOUT"
if MARKER in src:
    print("already patched - no change"); sys.exit(0)

OLD_RULES = '''- Use ONLY the facts stated in the documents provided. Add nothing that is not in them.
- Do NOT infer, guess, or assert WHY something happened. If the documents do not state a
  cause, do not state one. Report only what the documents say.
- Every sentence MUST end with a citation to the document(s) it draws from, written exactly
  as the listed id in square brackets, e.g. [doc_0012]. A sentence may cite more than one:
  [doc_0012][doc_0099].
- Never write a document id that is not in the provided list.
- At most {max_sentences} sentences. Output ONLY the summary - no preamble, no markdown.
- If the documents do not actually address the question, output exactly: CANNOT_SUMMARIZE"""'''

NEW_RULES = '''- Use ONLY the facts stated in the documents provided. Add nothing that is not in them.
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
  Delays were 3, 4, and 7 days for SH-4415, SH-4962, and SH-4439 [doc_0012].'''

n = src.count(OLD_RULES)
assert n == 1, f"OLD_RULES anchor matched {n}x (expected 1) - aborting"
src = src.replace(OLD_RULES, NEW_RULES)
open(P, "w", encoding="utf-8").write(src)
print("patched summary prompt -> qualitative + same-sentence citations")
