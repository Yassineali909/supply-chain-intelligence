"""
sql_executor.py — Layer 1 (read-only execution) + the timeout half of Layer 4.

This is the LAST line of defense: even if a write somehow slipped past the parser-based
guardrail (sql_guardrail.py), Postgres itself must reject it. We enforce read-only two
ways (belt and suspenders):

  1. `default_transaction_read_only=on` passed as a libpq session option, so the whole
     session runs read-only from the first statement.
  2. `conn.read_only = True` on the psycopg connection object.

and the statement timeout (Layer 4) is set as a session option so a runaway query can't
exhaust resources regardless of what the planner does.

PRODUCTION UPGRADE (documented, not done here, per the agreed decision): run this under a
dedicated SELECT-only Postgres role. Transaction-level read-only is the right weight for a
local portfolio build; a role is the production-grade control.

NOTE: this uses psycopg (v3) directly for explicit read-only control. If you'd rather route
through the existing `postgres_tool._run()` helper for consistency, paste that file and I'll
align it — the only hard requirement is that read-only + timeout are set before execution.
"""

from __future__ import annotations

from typing import Any

DEFAULT_TIMEOUT_MS = 5000


class ReadOnlyViolation(RuntimeError):
    """A write was attempted against the read-only session (Layer 1 did its job)."""


class QueryTimeout(RuntimeError):
    """The statement exceeded the Layer 4 timeout."""


class SchemaError(RuntimeError):
    """The query referenced a column/table that doesn't exist (hallucinated schema)."""


def _conninfo(database_url: str) -> str:
    """Accept either the plain libpq URL or the SQLAlchemy `+psycopg` URL."""
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def execute_readonly(
    database_url: str,
    safe_sql: str,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> tuple[list[str], list[tuple[Any, ...]]]:
    """Execute already-validated SQL under a read-only, time-limited session.

    Returns (column_names, rows). Raises ReadOnlyViolation / QueryTimeout / SchemaError
    for the cases the caller refuses on, or psycopg.Error for anything else.

    `safe_sql` MUST be the output of sql_guardrail.validate_sql(...).safe_sql. This function
    does not validate; it is the execution boundary, not the gate.
    """
    import psycopg
    from psycopg import errors as pgerr

    options = f"-c default_transaction_read_only=on -c statement_timeout={int(timeout_ms)}"
    try:
        with psycopg.connect(_conninfo(database_url), options=options) as conn:
            conn.read_only = True  # suspenders, in addition to the session option (belt)
            with conn.cursor() as cur:
                cur.execute(safe_sql)  # type: ignore[arg-type]
                columns = [d.name for d in cur.description] if cur.description else []
                rows = cur.fetchall() if cur.description else []
                return columns, rows
    except pgerr.ReadOnlySqlTransaction as exc:
        raise ReadOnlyViolation(str(exc)) from exc
    except pgerr.QueryCanceled as exc:  # statement_timeout fires as QueryCanceled
        raise QueryTimeout(str(exc)) from exc
    except (pgerr.UndefinedColumn, pgerr.UndefinedTable, pgerr.UndefinedFunction) as exc:
        raise SchemaError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Live self-check (build-order step 2). Run this on the WSL stack:
#     python -m rc07_vertical_slice.sql_executor
# It proves the DB rejects a write EVEN WHEN the validator is bypassed on purpose.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    DB = "postgresql://yassine:devpass@localhost:5432/meridian"

    print("1) a benign SELECT should return rows:")
    cols, rows = execute_readonly(DB, "SELECT COUNT(*) AS n FROM shipments LIMIT 1")
    print(f"   columns={cols} rows={rows}  -> OK\n")

    print("2) a WRITE, deliberately bypassing the validator, must be rejected by the DB:")
    try:
        execute_readonly(DB, "DELETE FROM shipments WHERE false")
        print("   *** FAIL: the write was NOT rejected — Layer 1 is not holding ***")
        sys.exit(1)
    except ReadOnlyViolation as exc:
        print(f"   blocked at the DB level as expected: {str(exc).splitlines()[0]}")

    print("\n3) statement_timeout should abort a deliberately slow query:")
    try:
        # pg_sleep is on the validator denylist, but we bypass the validator here to test
        # the timeout layer in isolation.
        execute_readonly(DB, "SELECT pg_sleep(30)", timeout_ms=1000)
        print("   *** FAIL: the slow query was not aborted — Layer 4 timeout not holding ***")
        sys.exit(1)
    except QueryTimeout:
        print("   aborted by statement_timeout as expected.")

    print("\nLayer 1 + Layer 4 (timeout) confirmed on the live DB.")
