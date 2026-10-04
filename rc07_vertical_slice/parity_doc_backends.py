"""
parity_doc_backends.py — prove RC-07 and RC-06 behave IDENTICALLY on the JSON and Qdrant
document backends, before trusting the migration. Run AFTER patch_document_retrieval.py and
after build_qdrant_index.py has created ./qdrant_data.

    python parity_doc_backends.py

Compares outcome + the set of evidence facts for each shipment under both backends.
"""
import os
import document_retrieval as dr
from rc07 import investigate_rc07

DB = "postgresql+psycopg://yassine:devpass@localhost:5432/meridian"
ROOT = "../artifacts/documents"
# a DOCUMENTED customs-hold shipment (RC-07 style) + a known RC-06 shipment (no direct doc)
CODES = ["SH-6968", "SH-4493"]


def run(code, use_qdrant):
    os.environ["USE_QDRANT"] = "1" if use_qdrant else ""
    dr._store = None            # reset the cached backend between runs
    dr._warned = False
    r = investigate_rc07(DB, ROOT, code)
    return r.outcome.value, sorted(e.fact for e in r.evidence)


ok = 0
for code in CODES:
    j_out, j_ev = run(code, False)
    q_out, q_ev = run(code, True)
    match = (j_out == q_out and j_ev == q_ev)
    ok += match
    print(f"\n{code}:")
    print(f"  JSON  : {j_out}  ({len(j_ev)} evidence)")
    print(f"  QDRANT: {q_out}  ({len(q_ev)} evidence)")
    print(f"  -> {'MATCH' if match else '*** DIFF ***'}")

print(f"\nPARITY: {ok}/{len(CODES)} shipments identical across backends "
      f"{'— migration safe' if ok == len(CODES) else '— DO NOT rely on Qdrant backend yet'}")
