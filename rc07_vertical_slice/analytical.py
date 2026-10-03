"""
analytical.py — the GENERAL analytical investigation (text-to-SQL), plus the router
precedence predicate for the new `analytical` route.

Flow (Option A, deliberately bent): the LLM DRAFTS SQL -> the guardrail VALIDATES ->
read-only execution -> AGGREGATE claim(s) built from the result -> the verifier gates
them. At every failure point it REFUSES (INSUFFICIENT_EVIDENCE) rather than guess.

Result shapes supported:
  * SCALAR — one row, one column (counts, averages, sums): a single AGGREGATE claim.
  * GROUPED — a `GROUP BY` query returning N rows x 2 columns (label, value), e.g.
    "average delay per carrier", "count per status", "avg delay per month": ONE AGGREGATE
    claim PER ROW, each verified against its own SQL value. The group label lives in the
    evidence LOCATOR, never the scanned claim text, so a numeric label (a month number)
    can never pollute the value the verifier reads. Capped at MAX_GROUPS rows — a table
    answer is only honest if a human can audit it.

Anything else (2 columns with no GROUP BY -> looks like two separate metrics; 3+ columns;
a non-numeric value column; an empty result) is refused rather than guessed.

Honesty note carried into the answer: the AGGREGATE check guarantees each claimed value is
exactly what the SQL returned (transcription), NOT that the SQL semantically answers the
question. The generated SQL is surfaced in the answer and evidence locator so that residual
risk is auditable rather than hidden.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

import sqlglot
from sqlglot import exp

from agent_contract import (
    AgentResponse, Claim, ClaimType, Evidence, Outcome, Relevance,
    SourceType, SupportStatus, Timing, ToolTraceEntry, Verification,
)
from analytical_draft import draft_and_validate, load_schema
from sql_executor import (
    execute_readonly, ReadOnlyViolation, QueryTimeout, SchemaError,
)
from verifier import verify_response

# A grouped answer is only honest if a human can actually audit every row.
MAX_GROUPS = 25


# ---------------------------------------------------------------------------
# Router precedence predicate (step 5). Pure function, no router dependency.
# ---------------------------------------------------------------------------

_SCENARIO_ENTITY_RE = re.compile(r"\bS\d{2,}\b|\bSH-\d+\b|\bWH-\d+\b|\bPORT-[A-Z]+\b|\bCR\d+\b")
_COUNT_LEAD_RE = re.compile(r"\b(how many|number of|count of|total number of)\b", re.IGNORECASE)
_TABLE_NOUN_RE = re.compile(
    r"\b(shipments?|deliver(?:y|ies)|invoices?|orders?|purchase orders?|incidents?|"
    r"suppliers?|customers?|routes?|carriers?|ports?|warehouses?|products?)\b",
    re.IGNORECASE,
)
_AGG_RE = re.compile(
    r"\b(average|avg|mean|median|total|sum|proportion|percentage|percent|distribution)\b",
    re.IGNORECASE,
)


def is_analytical_question(question: str) -> bool:
    """True if this is a general aggregate/count question the 7 scenarios don't own.

    1. A row-count of a table ("how many shipments used CR3") — never a scenario.
    2. An aggregate ("average delay in March") with NO scenario entity named — so
       "average delay for S07" stays with the supplier scenario, by design.
    The router adds the remaining guard (impact/graph co-exposure wins over this).
    """
    if _COUNT_LEAD_RE.search(question) and _TABLE_NOUN_RE.search(question):
        return True
    if _AGG_RE.search(question) and not _SCENARIO_ENTITY_RE.search(question):
        return True
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_id() -> str:
    return "RUN-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _fmt(value: float) -> str:
    """Render a numeric value without a thousands separator; integers without a decimal."""
    f = float(value)
    return str(int(f)) if f.is_integer() else f"{f:g}"


def _is_grouped(sql: str) -> bool:
    """True if the (already-validated) SQL contains a GROUP BY clause."""
    try:
        return sqlglot.parse_one(sql, dialect="postgres").find(exp.Group) is not None
    except Exception:
        return False


def _refuse(question, answer, started, tool_ms, trace):
    return AgentResponse(
        run_id=_run_id(), question=question, outcome=Outcome.INSUFFICIENT_EVIDENCE,
        answer=answer, claims=[], evidence=[], tool_trace=trace,
        verification=Verification(status="FAILED", checks=[]),
        timing=Timing(total_ms=int((time.perf_counter() - started) * 1000), tool_ms=tool_ms),
    )


def _sql_error_trace(safe_sql, draft_result, reason):
    return ToolTraceEntry(
        step=1, tool_call_id="TC-SQL", tool="query_database",
        purpose="execute the validated analytical SQL", status="ERROR",
        input={"generated_sql": safe_sql, "error": reason, "attempts": draft_result.attempts},
        output_refs=[],
    )


def _success_trace(safe_sql, draft_result, refs):
    return ToolTraceEntry(
        step=1, tool_call_id="TC-SQL", tool="query_database",
        purpose="execute the validated analytical SQL", status="SUCCESS",
        input={"generated_sql": safe_sql, "drafts": list(draft_result.drafts),
               "attempts": draft_result.attempts},
        output_refs=refs,
    )


# ---------------------------------------------------------------------------
# The investigation (step 4 + multi-row)
# ---------------------------------------------------------------------------

def investigate_analytical(
    llm_call,
    database_url: str,
    question: str,
    *,
    schema: dict[str, list[str]] | None = None,
    draft=draft_and_validate,
    execute=execute_readonly,
    max_attempts: int = 2,
) -> AgentResponse:
    """Answer a general analytical question via guardrail-validated LLM-drafted SQL.

    Hooks (`schema`, `draft`, `execute`) are injectable for hermetic testing; in production
    they default to the live implementations.
    """
    started = time.perf_counter()
    tool_ms = 0

    if schema is None:
        schema = load_schema(database_url)

    # --- draft + validate (step 3) ----------------------------------------------------
    t0 = time.perf_counter()
    d = draft(llm_call, question, schema, max_attempts=max_attempts)
    tool_ms += int((time.perf_counter() - t0) * 1000)

    if not d.ok:
        trace = [ToolTraceEntry(
            step=1, tool_call_id="TC-SQL", tool="query_database",
            purpose="draft and validate analytical SQL", status="ERROR",
            input={"drafts": list(d.drafts), "rejection": d.reason, "attempts": d.attempts},
            output_refs=[])]
        return _refuse(question,
                       f"I could not produce a safe query for this question: {d.reason}. "
                       f"No SQL was executed.", started, tool_ms, trace)

    safe_sql = d.safe_sql

    # --- Layer 1 execution (read-only, capped, timed) ---------------------------------
    t0 = time.perf_counter()
    try:
        columns, rows = execute(database_url, safe_sql)
    except ReadOnlyViolation:
        tool_ms += int((time.perf_counter() - t0) * 1000)
        return _refuse(question,
                       "The generated query attempted a write and was rejected by the "
                       "read-only execution layer. No data was changed.",
                       started, tool_ms, [_sql_error_trace(safe_sql, d, "read-only violation")])
    except QueryTimeout:
        tool_ms += int((time.perf_counter() - t0) * 1000)
        return _refuse(question, "The generated query exceeded the time limit and was aborted.",
                       started, tool_ms, [_sql_error_trace(safe_sql, d, "statement timeout")])
    except SchemaError as exc:
        tool_ms += int((time.perf_counter() - t0) * 1000)
        return _refuse(question,
                       f"The generated query referenced something that does not exist "
                       f"({str(exc).splitlines()[0]}). Refusing rather than guess.",
                       started, tool_ms, [_sql_error_trace(safe_sql, d, "schema error")])
    except Exception as exc:
        tool_ms += int((time.perf_counter() - t0) * 1000)
        return _refuse(question,
                       f"The generated query could not be executed ({type(exc).__name__}). "
                       f"Refusing rather than guess.",
                       started, tool_ms, [_sql_error_trace(safe_sql, d, "execution error")])
    tool_ms += int((time.perf_counter() - t0) * 1000)

    # --- decide the result shape ------------------------------------------------------
    ncols = len(columns)
    nrows = len(rows)

    if nrows == 0:
        return _refuse(question, "The query returned no rows. Refusing rather than guess.",
                       started, tool_ms, [_success_trace(safe_sql, d, [])])

    label_col = None  # set for grouped results

    # SCALAR: one row, one column.
    if ncols == 1 and nrows == 1:
        raw = rows[0][0]
        if raw is None:
            return _refuse(question, "The query returned no value (empty result). "
                           "Refusing rather than guess.",
                           started, tool_ms, [_success_trace(safe_sql, d, [])])
        groups = [(None, float(raw))]

    # GROUPED: a GROUP BY query returning label + value columns.
    elif ncols == 2 and _is_grouped(safe_sql):
        if nrows > MAX_GROUPS:
            return _refuse(question,
                           f"The query returned {nrows} groups, more than the {MAX_GROUPS} "
                           f"this path will present (a table answer must stay auditable). "
                           f"Narrow the question.",
                           started, tool_ms, [_success_trace(safe_sql, d, [])])
        label_col = columns[0]
        try:
            groups = []
            for r in rows:
                if r[1] is None:
                    raise ValueError("null value in a group")
                groups.append((r[0], float(r[1])))   # last column is the value, by convention
        except (TypeError, ValueError):
            return _refuse(question,
                           "The grouped query's value column is not numeric (or has gaps); "
                           "refusing rather than guess which column is the answer.",
                           started, tool_ms, [_success_trace(safe_sql, d, [])])

    else:
        return _refuse(question,
                       f"The query returned {nrows} row(s) and {ncols} column(s) in a shape "
                       f"this path can't verify (it answers a single value, or a GROUP BY "
                       f"breakdown of label + value). Refusing rather than over-summarize.",
                       started, tool_ms, [_success_trace(safe_sql, d, [])])

    # --- build evidence + AGGREGATE claim(s) ------------------------------------------
    evidences, claims, refs = [], [], []
    for i, (label, value) in enumerate(groups):
        eid, cid = f"EVD-{i}", f"CLM-{i}"
        refs.append(eid)
        vstr = _fmt(value)
        locator = {"generated_sql": safe_sql, "attempts": d.attempts}
        if label is not None:
            locator["group"] = str(label)
            locator["group_column"] = label_col
            locator["value_column"] = columns[1]
        else:
            locator["column"] = columns[0]
        # The scanned fact/claim carry ONLY the value as a standalone number. The group
        # label (which may itself be numeric, e.g. a month) stays in the locator.
        evidences.append(Evidence(
            evidence_id=eid, source_type=SourceType.SQL, source_ref="postgres:analytical",
            locator=locator,
            fact=(f"The validated query returned {vstr} for this group."
                  if label is not None else f"The validated query returned {vstr}."),
            relevance=Relevance.DIRECT,
        ))
        claims.append(Claim(
            claim_id=cid,
            text=(f"For one group in the result, the value is {vstr}."
                  if label is not None
                  else f"The query answering this question returned a value of {vstr}."),
            claim_type=ClaimType.AGGREGATE, support_status=SupportStatus.SUPPORTED,
            evidence_ids=[eid],
        ))

    trace = [_success_trace(safe_sql, d, refs)]

    if label_col is None:  # scalar
        answer = (
            f"Based on a generated, guardrail-validated SQL query executed read-only, the "
            f"answer is {_fmt(groups[0][1])}. The query was: {safe_sql}  "
            f"(This confirms the value returned by that specific query; it does not by itself "
            f"certify the query is the only correct reading of the question.)"
        )
    else:  # grouped
        lines = "\n".join(f"  - {label}: {_fmt(value)}" for label, value in groups)
        answer = (
            f"Based on a generated, guardrail-validated SQL query executed read-only, here is "
            f"the breakdown ({label_col} -> {columns[1]}):\n{lines}\n"
            f"The query was: {safe_sql}  (Each value is confirmed against that query; this "
            f"does not by itself certify the query is the only correct reading of the question.)"
        )

    resp = AgentResponse(
        run_id=_run_id(), question=question, outcome=Outcome.SUPPORTED, answer=answer,
        claims=claims, evidence=evidences, tool_trace=trace,
        verification=Verification(status="FAILED", checks=[]),
        timing=Timing(total_ms=int((time.perf_counter() - started) * 1000), tool_ms=tool_ms),
    )
    verified = verify_response(resp)
    verified.tool_trace.append(ToolTraceEntry(
        step=len(trace) + 1, tool_call_id="TC-VERIFY", tool="verify_evidence",
        purpose="check each aggregate claim's value against its SQL evidence",
        status="SUCCESS" if verified.verification.status == "PASSED" else "ERROR",
        input={"claim_ids": [c.claim_id for c in verified.claims]}, output_refs=[],
    ))
    return verified
