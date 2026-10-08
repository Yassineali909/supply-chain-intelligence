"""stack_smoke.py - end-to-end check of the Docker stack. Run inside the app container:
    docker compose run --rm --no-deps app python stack_smoke.py
Asserts the expected outcome per question; exits 1 on any mismatch."""
import os, sys, time
from router import investigate
from ollama_llm import ollama_call

DB = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://", 1)
DOCS = "../artifacts/documents"   # intentionally absent here: lookups must go through Qdrant

CASES = [
    ("What happened to shipment SH-6968?", "SUPPORTED"),
    ("What happened to shipment SH-4493?", "INSUFFICIENT_EVIDENCE"),   # RC-06: must refuse
    ("Why is supplier S07 chronically late?", "SUPPORTED"),
    ("Which customers are affected by port congestion through shared routes?", "SUPPORTED"),
    ("how many shipments used CR3?", "SUPPORTED"),
    ("what do our documents say about customs holds?", "SUPPORTED"),
    ("What is the capital of France?", "INSUFFICIENT_EVIDENCE"),
]

failed = 0
for q, expected in CASES:
    t0 = time.time()
    try:
        r = investigate(ollama_call, DB, DOCS, q)
        got = r.outcome.value
        note = r.answer[:90].replace("\n", " ")
    except Exception as e:
        got, note = "CRASH", f"{type(e).__name__}: {str(e)[:100]}"
    ok = (got == expected)
    failed += (not ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {time.time()-t0:5.1f}s {got:22s} (want {expected}) | {q}")
    if not ok:
        print("        ", note)

print(f"\n{len(CASES)-failed}/{len(CASES)} passed")
sys.exit(1 if failed else 0)
