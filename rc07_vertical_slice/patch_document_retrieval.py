"""
patch_document_retrieval.py — point the investigations at the backend switch.

Swaps `from document_store import search_documents` -> `from document_retrieval import
search_documents` in rc07.py and planner.py. document_retrieval defaults to the JSON store,
so behavior is UNCHANGED until you set USE_QDRANT=1. Guarded (B12): each anchor must match
exactly once and the replacement must not already be present; idempotent.
"""
import sys

EDITS = {
    "rc07.py": [("from document_store import search_documents",
                 "from document_retrieval import search_documents")],
    "planner.py": [("from document_store import search_documents",
                    "from document_retrieval import search_documents")],
}


def patch(path, edits):
    src = open(path, encoding="utf-8").read()
    if all(new in src for _, new in edits):
        print(f"{path}: already patched."); return 0
    staged = src
    for anchor, new in edits:
        if new in staged:
            continue
        c = staged.count(anchor)
        if c != 1:
            print(f"{path}: ABORT anchor matched {c} time(s), expected 1."); return 1
        staged = staged.replace(anchor, new, 1)
    open(path, "w", encoding="utf-8").write(staged)
    print(f"{path}: import swapped to document_retrieval.")
    return 0


def main():
    rc = 0
    for path, edits in EDITS.items():
        rc |= patch(path, edits)
    return rc


if __name__ == "__main__":
    sys.exit(main())
