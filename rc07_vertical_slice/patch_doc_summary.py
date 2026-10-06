import sys

def patch(path, edits):
    src = open(path, encoding="utf-8").read()
    for name, old, new in edits:
        if new in src:
            print(f"  [{path}] {name}: already present, skipping"); continue
        n = src.count(old)
        assert n == 1, f"[{path}] {name}: anchor matched {n}x (expected 1) -- aborting"
        src = src.replace(old, new)
        print(f"  [{path}] {name}: patched")
    bad = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
    assert not bad, f"[{path}] non-ASCII at {bad[:3]} -- aborting"
    open(path, "w", encoding="utf-8").write(src)

SEM = "semantic.py"

imp_old = "from verifier import verify_response"
imp_new = ("from verifier import verify_response\n"
           "from summary_draft import draft_and_verify_summary")

sig_old = ("def investigate_doc_search(question: str, *, store=None, top_k: int = TOP_K,\n"
           "                           score_floor: float = SCORE_FLOOR) -> AgentResponse:\n"
           "    started = time.perf_counter()")
sig_new = ("def investigate_doc_search(question: str, *, store=None, top_k: int = TOP_K,\n"
           "                           score_floor: float = SCORE_FLOOR,\n"
           "                           summarize: bool = None, llm_call=None) -> AgentResponse:\n"
           "    started = time.perf_counter()\n"
           "    if summarize is None:\n"
           "        summarize = os.environ.get('USE_DOC_SUMMARY') == '1'")

attach_old = "    trace = [ToolTraceEntry("
attach_new = (
    "    summary_trace = None\n"
    "    if summarize and llm_call is not None:\n"
    "        retrieved_map = {str(d.get('doc_id', f'doc-{i}')): str(d.get('text', ''))\n"
    "                         for i, (d, _) in enumerate(relevant)}\n"
    "        sres = draft_and_verify_summary(llm_call, question, retrieved_map)\n"
    "        if sres.ok:\n"
    "            answer = ('Summary (unverified synthesis over the cited documents below): '\n"
    "                      + sres.summary + chr(10) + chr(10) + answer)\n"
    "            summary_trace = {'status': 'grounded', 'attempts': sres.attempts,\n"
    "                             'cited': list(sres.cited_doc_ids)}\n"
    "        else:\n"
    "            summary_trace = {'status': 'suppressed', 'attempts': sres.attempts,\n"
    "                             'reason': sres.reason}\n"
    "\n"
    "    trace = [ToolTraceEntry(")

trace_old = ('        input={"claim_ids": ["CLM-DOC"]}, output_refs=[]))\n'
             "    return verified")
trace_new = ('        input={"claim_ids": ["CLM-DOC"]}, output_refs=[]))\n'
             "    if summary_trace is not None:\n"
             "        verified.tool_trace.append(ToolTraceEntry(\n"
             '            step=3, tool_call_id="TC-SUMMARY", tool="search_documents",\n'
             '            purpose="grounded summary synthesis (G1-G3 gated)",\n'
             "            status=\"SUCCESS\" if summary_trace['status'] == 'grounded' else \"SKIPPED\",\n"
             "            input=summary_trace, output_refs=[]))\n"
             "    return verified")

patch(SEM, [
    ("import", imp_old, imp_new),
    ("signature+env", sig_old, sig_new),
    ("summary-step", attach_old, attach_new),
    ("summary-trace-entry", trace_old, trace_new),
])

patch("router.py", [
    ("dispatch", "        resp = investigate_doc_search(question)",
                 "        resp = investigate_doc_search(question, llm_call=llm_call)"),
])
print("done")
