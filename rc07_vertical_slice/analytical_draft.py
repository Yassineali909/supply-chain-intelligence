"""
analytical_draft.py — Step 3 of the text-to-SQL build: the LLM DRAFTS, the guardrail
CONTROLS.

This is the one place in the whole system where the LLM is allowed to write SQL. The
safety story is that its output is NEVER trusted: the model is given a schema-aware prompt
that lists ONLY the allowlisted tables and their columns, and whatever it returns is
stripped of markdown/prose and handed to sql_guardrail.validate_sql(). A draft that fails
any guardrail layer is refused (optionally after one bounded re-prompt that tells the model
why it was rejected). Nothing reaches the database until validation passes.

Design choices:
  * The schema shown to the model is loaded from the LIVE database (information_schema),
    restricted to the allowlist. That keeps the prompt grounded in the real columns and
    means it automatically omits the stripped hidden-lever columns (they aren't in the
    schema). load_schema() is OUR parameterized, read-only introspection query — it is not
    LLM output, so it legitimately reads information_schema that the guardrail forbids for
    drafted SQL.
  * `llm_call` is injected (a callable `(system, user) -> str`), so this module is testable
    with a mock and carries no hard dependency on Ollama. The investigation passes the real
    `ollama_llm.ollama_call`.
  * One bounded retry. A first invalid draft is re-prompted once with the rejection reason;
    the retry is validated exactly like the first. This cuts false refusals without
    loosening any guard. Set max_attempts=1 to disable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from sql_guardrail import BUSINESS_TABLES, MAX_LIMIT, validate_sql

LLMCall = Callable[[str, str], str]


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DraftResult:
    """Outcome of drafting + validating SQL for one question.

    ok=True  -> `safe_sql` is validated and LIMIT-enforced, ready for sql_executor.
    ok=False -> `reason` explains the refusal (last guardrail rejection, or a drafting
                failure). `drafts` holds every raw LLM attempt, for the tool_trace.
    """
    ok: bool
    safe_sql: Optional[str] = None
    reason: Optional[str] = None
    referenced_tables: tuple[str, ...] = ()
    drafts: tuple[str, ...] = ()
    attempts: int = 0


# ---------------------------------------------------------------------------
# Schema introspection (grounds the prompt in the real columns)
# ---------------------------------------------------------------------------

def load_schema(
    database_url: str,
    allowed_tables: frozenset[str] = BUSINESS_TABLES,
) -> dict[str, list[str]]:
    """Return {table: [columns]} for the allowlisted tables, read from the live DB.

    Parameterized and read-only. This is trusted internal introspection, not drafted SQL.
    """
    import psycopg

    conninfo = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    schema: dict[str, list[str]] = {}
    with psycopg.connect(conninfo, options="-c default_transaction_read_only=on") as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = ANY(%s)
                ORDER BY table_name, ordinal_position
                """,
                (list(allowed_tables),),
            )
            for table_name, column_name in cur.fetchall():
                schema.setdefault(table_name, []).append(column_name)
    return schema


def build_schema_prompt(schema: dict[str, list[str]]) -> str:
    """Render the allowlisted schema as a compact block for the system prompt."""
    lines = [f"- {t}({', '.join(cols)})" for t, cols in sorted(schema.items())]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------

_SYSTEM_TEMPLATE = """You translate a business question into ONE PostgreSQL SELECT query.

STRICT RULES:
- Output ONLY the SQL. No prose, no explanation, no markdown fences.
- Exactly ONE statement, and it MUST be a SELECT (never INSERT/UPDATE/DELETE/DDL).
- Use ONLY these tables and columns (nothing else exists for you):
{schema}
- Do not reference system catalogs, information_schema, or any other database.
- Prefer an explicit aggregate (COUNT/AVG/SUM) when the question asks "how many" or "average".
- If the question cannot be answered from these tables, output exactly: CANNOT_ANSWER

EXAMPLES (follow these patterns — count from the main fact table, join only to resolve a code, and qualify every column to the table it belongs to):
Q: How many shipments used carrier CR3?
SQL: SELECT COUNT(*) FROM shipments s JOIN carriers c ON s.carrier_id = c.carrier_id WHERE c.code = 'CR3'
Q: How many shipments were carried by CR3?
SQL: SELECT COUNT(*) FROM shipments s JOIN carriers c ON s.carrier_id = c.carrier_id WHERE c.code = 'CR3'
Q: How many invoices are disputed?
SQL: SELECT COUNT(*) FROM invoices WHERE status = 'disputed'
Q: What is the average delay across all shipments?
SQL: SELECT AVG(delay_days) FROM shipments
"""

_RETRY_SUFFIX = """

Your previous attempt was REJECTED by a safety check:
    {reason}
The rejected SQL was:
    {bad_sql}
Produce a corrected single read-only SELECT over only the allowed tables. SQL only."""


def _build_system(schema: dict[str, list[str]]) -> str:
    return _SYSTEM_TEMPLATE.format(schema=build_schema_prompt(schema))


# ---------------------------------------------------------------------------
# Extracting SQL from a model response
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:sql)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_SQL_START_RE = re.compile(r"(?is)\b(SELECT|WITH)\b")


def extract_sql(text: str) -> str:
    """Pull the SQL out of a model response that may be fenced or prose-wrapped."""
    if text is None:
        return ""
    t = text.strip()
    # Prefer a fenced block if present.
    m = _FENCE_RE.search(t)
    if m:
        t = m.group(1).strip()
    # Drop any leading prose before the first SELECT/WITH.
    m2 = _SQL_START_RE.search(t)
    if m2:
        t = t[m2.start():].strip()
    # Trim a single trailing semicolon + whitespace (the validator accepts one statement
    # either way, but this keeps the stored SQL clean).
    return t.rstrip().rstrip(";").rstrip()


# ---------------------------------------------------------------------------
# The draft -> validate pipeline
# ---------------------------------------------------------------------------

# Sentinel the model is told to emit when the question is unanswerable from the schema.
_CANNOT_ANSWER = "CANNOT_ANSWER"


def draft_and_validate(
    llm_call: LLMCall,
    question: str,
    schema: dict[str, list[str]],
    *,
    allowed_tables: frozenset[str] = BUSINESS_TABLES,
    max_limit: int = MAX_LIMIT,
    max_attempts: int = 2,
) -> DraftResult:
    """Draft SQL with the LLM and validate it through the guardrail, with bounded retry.

    `schema` is {table: [columns]} (from load_schema). `llm_call(system, user)` returns the
    model's raw text. Returns a DraftResult; the caller executes `safe_sql` only when ok.
    """
    system = _build_system(schema)
    drafts: list[str] = []
    last_reason = "no draft produced"
    bad_sql = ""

    for attempt in range(1, max_attempts + 1):
        user = question if attempt == 1 else (
            question + _RETRY_SUFFIX.format(reason=last_reason, bad_sql=bad_sql))
        raw = llm_call(system, user)
        drafts.append(raw if raw is not None else "")

        candidate = extract_sql(raw)

        # The model explicitly declined — honest refusal, no execution.
        if candidate.strip().upper().startswith(_CANNOT_ANSWER):
            return DraftResult(
                ok=False,
                reason="the question cannot be answered from the allowed tables",
                drafts=tuple(drafts),
                attempts=attempt,
            )

        result = validate_sql(candidate, allowed_tables=allowed_tables, max_limit=max_limit)
        if result.ok:
            return DraftResult(
                ok=True,
                safe_sql=result.safe_sql,
                referenced_tables=result.referenced_tables,
                drafts=tuple(drafts),
                attempts=attempt,
            )

        # Rejected — remember why, and (if attempts remain) re-prompt with the reason.
        last_reason = result.reason or "rejected by guardrail"
        bad_sql = candidate

    return DraftResult(
        ok=False,
        reason=f"drafted SQL failed validation after {max_attempts} attempt(s): {last_reason}",
        drafts=tuple(drafts),
        attempts=max_attempts,
    )
