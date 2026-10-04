"""
patch_semantic_route.py — add the `doc_search` route to router.py. Guarded (B12), idempotent.
Must be applied AFTER patch_router.py (it anchors on the analytical route lines).
"""
import sys

EDITS = [
    # import
    ("from analytical import is_analytical_question, investigate_analytical",
     "from analytical import is_analytical_question, investigate_analytical\n"
     "from semantic import is_doc_search_question, investigate_doc_search"),
    # classify: doc_search wins over analytical/scenarios (content question, no entity)
    ('    _impact = any(k in ql for k in GRAPH_KEYWORDS) and "customer" in ql\n'
     '    if not _impact and is_analytical_question(question):\n'
     '        return "analytical"',
     '    _impact = any(k in ql for k in GRAPH_KEYWORDS) and "customer" in ql\n'
     '    if is_doc_search_question(question):\n'
     '        return "doc_search"\n'
     '    if not _impact and is_analytical_question(question):\n'
     '        return "analytical"'),
    # dispatch
    ('    elif qtype == "analytical":\n'
     '        resp = investigate_analytical(llm_call, database_url, question)',
     '    elif qtype == "doc_search":\n'
     '        resp = investigate_doc_search(question)\n'
     '    elif qtype == "analytical":\n'
     '        resp = investigate_analytical(llm_call, database_url, question)'),
]


def main():
    src = open("router.py", encoding="utf-8").read()
    if all(new in src for _, new in EDITS):
        print("router.py already has doc_search route."); return 0
    staged = src
    for anchor, new in EDITS:
        if new in staged:
            continue
        c = staged.count(anchor)
        if c != 1:
            print(f"ABORT: anchor matched {c} time(s), expected 1:\n  {anchor[:60]!r}"); return 1
        staged = staged.replace(anchor, new, 1)
    open("router.py", "w", encoding="utf-8").write(staged)
    print("router.py: doc_search route added (import + classify + dispatch).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
