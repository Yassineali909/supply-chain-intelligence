# START HERE — NEXT SESSION

## DONE (latest session): TEXT-TO-SQL — COMPLETE
Scalar + grouped analytical queries, live and measured.
- Layered guardrail (sqlglot parse / table allowlist / forced LIMIT). Layer 1 read-only +
  Layer 4 timeout CONFIRMED on the live DB (bypassed DELETE rejected; timeout aborts).
- AGGREGATE claim type + per-row verifier check (TRANSCRIPTION guard).
- Router `analytical` route; CR3 count-vs-carrier-scenario precedence handled.
- Flow: draft (LLM) -> guardrail validate -> read-only execute -> AGGREGATE claim(s) -> verify.
- Eval: dev 14/14, held-out 11/11 (incl. CR3 precedence boundary). 132 tests. Clean-clone verified.
- Drafter few-shot hardened x3, each measured 0/5 -> 5/5: CR3 "carried by", grouped drafting,
  "per/by -> GROUP BY" rule.
- Files: sql_guardrail.py, sql_executor.py, analytical_draft.py, analytical.py,
  patch_router.py, patch_verifier.py (+ tests/test_sql_guardrail, test_analytical_draft,
  test_analytical, test_analytical_router).

## KNOWN LIMIT (interview-relevant, be honest about it)
The AGGREGATE check guarantees the claim matches the SQL RESULT (transcription), NOT that the
SQL matches the question's INTENT. The semantic gap (threat #6) is mitigated by surfacing the
generated SQL in the answer + evidence locator, not closed by verification. Live example seen:
"how many shipments per status" once drafted COUNT(*) without GROUP BY — correct number, wrong
question — fixed via few-shot, but the class of risk remains and is documented, not hidden.

## STILL OPEN (quick, mine to do)
- Confirm the 16-table allowlist vs live schema (\dt) and fill BUSINESS_TABLES in sql_guardrail.py.
- Production upgrade (documented in sql_executor.py): a dedicated SELECT-only Postgres role
  instead of SET TRANSACTION READ ONLY.

## NEXT BUILD CANDIDATES
(a) Qdrant vector-store swap (document_store interface is stable).
(b) Docker Compose one-command stack.
(c) Demo video (Streamlit + Grafana) — highest-value non-code task.
(d) Multi-row analytical v2: 3+ column results, numeric-label time-series beyond 2 columns.
