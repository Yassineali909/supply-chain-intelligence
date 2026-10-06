from __future__ import annotations
import os, re
os.environ.setdefault("USE_QDRANT", "1")
from ollama_llm import ollama_call
from semantic import _default_store, SCORE_FLOOR, TOP_K
from summary_grounding import verify_summary_grounding, _content_tokens, _CITE_RE
from summary_draft import _build_system, _USER_TEMPLATE, extract_summary, _render_docs

QUESTIONS = [
    "what do our documents say about customs holds?",
    "what do the documents say about port congestion?",
    "what do our records say about warehouse capacity issues?",
    "what do the documents mention about carrier delays?",
    "what do our documents say about damaged shipments?",
]
PLANTED = [
    "The delay was caused by a labor strike at the port.",
    "Management approved a budget increase for new equipment.",
    "The shipment was rerouted through a quantum logistics hub.",
    "Weather forecasts predict storms next quarter.",
]

def rmap(store, q):
    hits = store.semantic_search(q, top_k=TOP_K)
    rel = [(d, s) for d, s in hits if s >= SCORE_FLOOR]
    return {str(d.get("doc_id", f"doc-{i}")): str(d.get("text", "")) for i, (d, _) in enumerate(rel)}

def corpus(r):
    c = set()
    for t in r.values(): c |= _content_tokens(t)
    return c

def novel(sentence, c):
    return _content_tokens(_CITE_RE.sub(' ', sentence)) - c

store = _default_store(); assert store is not None, "no Qdrant index"
grounded_ng = []
print("#"*72 + "\nREAL llama3.2 SUMMARIES\n" + "#"*72)
for q in QUESTIONS:
    r = rmap(store, q)
    if not r:
        print(f"\nQ: {q}\n  (no docs above floor) - skipped"); continue
    c = corpus(r)
    summary = extract_summary(ollama_call(_build_system(4),
                 _USER_TEMPLATE.format(question=q, docs=_render_docs(r))))
    _, verdicts = verify_summary_grounding(summary, r, novelty_slack=0)
    print(f"\nQ: {q}\n  retrieved ids: {list(r)}\n  summary: {summary}")
    for v in verdicts:
        nv = novel(v.sentence, c)
        soundfail = [x for x in v.reasons if x[:2] in ("G1","G2","G3")]
        print(f"    [{'SOUND-FAIL' if soundfail else 'sound-ok'}] {v.sentence}")
        if soundfail: print(f"         sound reasons: {soundfail}")
        print(f"         NG novel ({len(nv)}): {sorted(nv)}")
        if not soundfail: grounded_ng.append(len(nv))

print("\n" + "#"*72 + "\nPLANTED-UNGROUNDED\n" + "#"*72)
c0 = corpus(rmap(store, QUESTIONS[0])); planted_ng = []
for p in PLANTED:
    nv = novel(p, c0); planted_ng.append(len(nv))
    print(f"  novel({len(nv)}): {sorted(nv)}   <- {p}")

print("\n" + "#"*72 + "\nCALIBRATION (grounded = sound-gate-passing only)\n" + "#"*72)
print(f"  grounded NG counts: {sorted(grounded_ng)}")
print(f"  planted  NG counts: {sorted(planted_ng)}")
gmax = max(grounded_ng, default=0); pmin = min(planted_ng, default=0)
print(f"  grounded MAX={gmax}  planted MIN={pmin}")
print(f"  -> CLEAN GAP, suggested slack = {gmax}" if pmin > gmax
      else "  -> still OVERLAP among sound-ok sentences: inspect novel tokens before setting slack")
