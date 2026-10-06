"""patch_cite_re.py - citation regex matched only lowercase doc_, but the real corpus uses
DOC-###### (uppercase/hyphen), so G1 was blind to every real citation and 'DOC' leaked into
NG. Make it format-agnostic. Anchor-checked + idempotent."""
import sys
P = "summary_grounding.py"
OLD = "_CITE_RE = re.compile(r'\\[(doc_[0-9A-Za-z_]+)\\]')"
NEW = "_CITE_RE = re.compile(r'\\[([A-Za-z][\\w\\-]*)\\]')  # [DOC-002646] or [doc_0012]"
src = open(P, encoding="utf-8").read()
if NEW in src:
    print("already patched - no change"); sys.exit(0)
n = src.count(OLD)
assert n == 1, f"anchor matched {n}x (expected 1) - aborting, inspect manually"
open(P, "w", encoding="utf-8").write(src.replace(OLD, NEW))
print("patched _CITE_RE -> format-agnostic")
