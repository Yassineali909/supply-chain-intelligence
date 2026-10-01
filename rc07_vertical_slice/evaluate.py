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

import os
EVAL_FILE = Path(os.environ.get("EVAL_FILE",
    str(Path(__file__).parent / "evaluation" / "eval_questions.json")))


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


# ─────────────────────────── Judge-based quality layer (gated by control) ───────
def run_judge_eval(llm_call, database_url, document_root, judge_faithfulness=None,
                   corrupt_answer=None):
    """
    Faithfulness scoring across the eval set, GATED by a control test.

    The judge's faithfulness scores are only reported if the judge first passes a CONTROL:
    on at least one real SUPPORTED answer, it must score the real answer higher than a
    deliberately-corrupted version. If the control fails, the judge is deemed unreliable
    FOR THIS RUN and faithfulness is reported as 'not scored (judge failed control)'.
    This prevents reporting a meaningless number from a rubber-stamping judge.
    """
    import json
    from router import investigate
    if judge_faithfulness is None or corrupt_answer is None:
        from llm_judge import judge_faithfulness, corrupt_answer

    cases = json.loads(EVAL_FILE.read_text())

    supported = []
    for c in cases:
        resp = investigate(llm_call, database_url, document_root, c["question"])
        if resp.outcome.value == "SUPPORTED" and resp.evidence:
            supported.append((c, resp))

    if not supported:
        print("No SUPPORTED answers to judge.")
        return None

    c0, r0 = supported[0]
    facts0 = [e.fact for e in r0.evidence]
    real_s, _ = judge_faithfulness(r0.answer, facts0)
    bad_s, _ = judge_faithfulness(corrupt_answer(r0.answer), facts0)
    control_pass = (real_s is not None and bad_s is not None and real_s > bad_s)

    print("=" * 60)
    print("JUDGE-BASED FAITHFULNESS EVALUATION")
    print("=" * 60)
    print(f"Control (real>corrupted): real={real_s} bad={bad_s} -> "
          f"{'PASS' if control_pass else 'FAIL'}")
    print("-" * 60)

    if not control_pass:
        print("Judge FAILED its control this run -> faithfulness NOT scored (unreliable).")
        print("=" * 60)
        return {"control_pass": False, "scores": None}

    scores = []
    for c, resp in supported:
        facts = [e.fact for e in resp.evidence]
        s, reason = judge_faithfulness(resp.answer, facts)
        scores.append((c["id"], s))
        print(f"  {c['id']:18s} faithfulness={s}  ({reason[:50]})")
    print("-" * 60)
    valid = [s for _, s in scores if s is not None]
    if valid:
        print(f"Mean faithfulness: {sum(valid)/len(valid):.2f} (n={len(valid)}, control-validated)")
    print("=" * 60)
    return {"control_pass": True, "scores": scores}


if __name__ == "__main__" and "--judge" in __import__("sys").argv:
    from ollama_llm import ollama_call
    _DB = "postgresql+psycopg://yassine:devpass@localhost:5432/meridian"
    run_judge_eval(ollama_call, _DB, "../artifacts/documents")
