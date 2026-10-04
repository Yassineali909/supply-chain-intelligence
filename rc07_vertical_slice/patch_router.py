"""
patch_router.py — add the `analytical` route to router.py, safely.

Follows the project's scripted-patch discipline (B10/B12/B16): every anchor must match
EXACTLY ONCE and its replacement must NOT already be present; all edits are applied in
memory; the file is written only if ALL pass. A bad anchor aborts writing nothing.

Run once:  python patch_router.py
It is idempotent: a second run detects the edits are already present and exits cleanly.
"""
import sys

PATH = "router.py"

EDITS = [
    # (1) import the analytical entry points at the top of the module.
    (
        "from agent_contract import AgentResponse, Outcome, Verification, Timing",
        "from agent_contract import AgentResponse, Outcome, Verification, Timing\n"
        "from analytical import is_analytical_question, investigate_analytical",
    ),
    # (2) classify(): the analytical route wins over the strong-entity fallback (a count
    #     like "how many shipments used CR3" names CR3 yet is NOT the carrier scenario),
    #     but impact/graph co-exposure still wins over analytical.
    (
        "def classify(llm_call, question: str) -> str:\n"
        "    det = _deterministic_type(question)",

        "def classify(llm_call, question: str) -> str:\n"
        "    ql = question.lower()\n"
        "    _impact = any(k in ql for k in GRAPH_KEYWORDS) and \"customer\" in ql\n"
        "    if not _impact and is_analytical_question(question):\n"
        "        return \"analytical\"\n"
        "    det = _deterministic_type(question)",
    ),
    # (3) investigate(): dispatch the analytical type before the out-of-scope refusal.
    (
        "    else:\n"
        "        resp = _refusal(question)",

        "    elif qtype == \"analytical\":\n"
        "        resp = investigate_analytical(llm_call, database_url, question)\n"
        "    else:\n"
        "        resp = _refusal(question)",
    ),
]


def main() -> int:
    with open(PATH, "r", encoding="utf-8") as f:
        src = f.read()

    # Idempotency: if every replacement is already present, there is nothing to do.
    if all(new in src for _, new in EDITS):
        print("router.py already patched — nothing to do.")
        return 0

    staged = src
    for anchor, new in EDITS:
        if new in staged:
            print(f"SKIP (already present): {anchor[:48]!r}...")
            continue
        count = staged.count(anchor)
        if count != 1:
            print(f"ABORT: anchor matched {count} time(s), expected exactly 1:\n  {anchor[:70]!r}")
            return 1
        staged = staged.replace(anchor, new, 1)

    with open(PATH, "w", encoding="utf-8") as f:
        f.write(staged)
    print("router.py patched: analytical import + classify precedence + investigate dispatch.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
