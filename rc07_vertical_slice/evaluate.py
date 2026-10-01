"""
Objective evaluation harness for the investigation agent.

Runs each question in evaluation/eval_questions.json through the router and scores three
OBJECTIVE, deterministic metrics against known-correct expectations:

  1. Routing accuracy      - did it classify the question to the right investigation?
  2. Outcome accuracy      - did it reach the right verdict (SUPPORTED / INSUFFICIENT)?
  3. Verification integrity- when it answered SUPPORTED, did its own verifier PASS?

No LLM judge here (that is a later layer). These three are checkable against ground
truth, which is exactly why the scenarios were planted with known answers.

    python evaluate.py
"""
from __future__ import annotations

import json
from pathlib import Path

EVAL_FILE = Path(__file__).parent / "evaluation" / "eval_questions.json"


def run_eval(llm_call, database_url, document_root):
    from router import classify, investigate

    cases = json.loads(EVAL_FILE.read_text())
    rows = []
    routing_hits = outcome_hits = verify_ok = 0
    verify_applicable = 0

    for c in cases:
        qtype = classify(llm_call, c["question"])
        resp = investigate(llm_call, database_url, document_root, c["question"])

        routing_ok = (qtype == c["expected_type"])
        outcome_ok = (resp.outcome.value == c["expected_outcome"])
        routing_hits += routing_ok
        outcome_hits += outcome_ok

        v_note = "-"
        if resp.outcome.value == "SUPPORTED":
            verify_applicable += 1
            vok = (resp.verification.status == "PASSED")
            verify_ok += vok
            v_note = "PASS" if vok else "FAIL"

        rows.append((c["id"], routing_ok, outcome_ok, qtype, resp.outcome.value, v_note))

    n = len(cases)
    print("=" * 72)
    print("OBJECTIVE EVALUATION")
    print("=" * 72)
    print(f"{'case':16s} {'route':6s} {'outcome':8s} {'got_type':13s} {'got_outcome':22s} verify")
    print("-" * 72)
    for cid, rok, ook, gt, go, vn in rows:
        print(f"{cid:16s} {'OK' if rok else 'XX':6s} {'OK' if ook else 'XX':8s} {gt:13s} {go:22s} {vn}")
    print("-" * 72)
    print(f"Routing accuracy      : {routing_hits}/{n} ({100*routing_hits//n}%)")
    print(f"Outcome accuracy      : {outcome_hits}/{n} ({100*outcome_hits//n}%)")
    if verify_applicable:
        print(f"Verification integrity: {verify_ok}/{verify_applicable} "
              f"({100*verify_ok//verify_applicable}%)  (of SUPPORTED answers)")
    print("=" * 72)
    return routing_hits, outcome_hits, n


if __name__ == "__main__":
    from ollama_llm import ollama_call
    DB = "postgresql+psycopg://yassine:devpass@localhost:5432/meridian"
    DOCS = "../artifacts/documents"
    run_eval(ollama_call, DB, DOCS)
