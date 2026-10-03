"""
sql_guardrail.py — deterministic validation for LLM-drafted SQL (text-to-SQL).

THESIS (see 03_START_HERE_NEXT_SESSION.md section 6): every other investigation is
Option A — the LLM never writes SQL. Text-to-SQL deliberately breaks that: the LLM
DRAFTS SQL. This module is the deterministic layer that makes that safe. The LLM's
output is NEVER trusted; it is parsed, validated, and re-rendered from the AST, and
nothing reaches the database until it passes every check here.

This file is Layers 2-4 of the five-layer design. It is pure-Python and DB-free, so it
can be adversarially attacked offline (and is — see tests/test_sql_guardrail.py). The
other two layers live elsewhere:
  Layer 1 (read-only execution, SET TRANSACTION READ ONLY)  -> sql_executor.py
  Layer 5 (the verifier still gates the final claim)        -> verifier.py (existing)

Layers implemented here:
  Layer 2  PARSE, DON'T REGEX. sqlglot must parse the text to exactly ONE statement and
           that statement must be a plain SELECT. A parser catches ';'-stacked payloads
           and comment-hidden writes that a regex cannot, and correctly ALLOWS a benign
           ';' that lives inside a string literal.
  Layer 3  TABLE ALLOWLIST. Every table referenced in the AST (including inside CTEs and
           subqueries) must be one of the business tables, in an allowed schema, with no
           cross-database catalog. This is where pg_catalog / information_schema / system
           tables are blocked. CTE *names* are internal references and are skipped — but
           the real tables inside a CTE body are still checked.
  Layer 4  FORCED LIMIT. A missing LIMIT is injected; a LIMIT above the cap is lowered; a
           smaller user LIMIT is preserved. (The statement timeout — the other half of
           Layer 4 — is applied at execution time in sql_executor.py.)

Design properties worth stating at interview:
  * We EXECUTE THE RE-RENDERED AST, not the raw string. Only structure sqlglot understood
    and we validated survives the round-trip; comments and parser-unsupported clauses are
    dropped, so they cannot smuggle anything to the DB.
  * We REFUSE rather than run SQL we cannot validate. Every rejection returns a reason;
    the caller turns that into an honest INSUFFICIENT_EVIDENCE refusal, never a guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import sqlglot
from sqlglot import exp

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DIALECT = "postgres"

# Layer 4: the hard row cap injected/enforced on every query.
MAX_LIMIT = 1000

# Layer 3: the business-data allowlist. Nothing else is reachable.
#
# !!! CONFIRM AGAINST THE REAL SCHEMA BEFORE SHIPPING !!!
# The handoff says the DB has 16 tables; the 14 below are the ones visible in the
# architecture doc. Populate the remaining ones from the live DB with:
#     SELECT table_name FROM information_schema.tables
#     WHERE table_schema = 'public' ORDER BY table_name;
# Deliberately EXCLUDED: the `runs` log table (agent infrastructure, not business data —
# the analytical path must not let the LLM query our own run history) and every hidden-
# lever column, which are already stripped from the schema upstream.
BUSINESS_TABLES = frozenset({
    "suppliers",
    "customers",
    "products",
    "ports",
    "warehouses",
    "carriers",
    "routes",
    "purchase_orders",
    "order_items",
    "shipments",
    "deliveries",
    "invoices",
    "incidents",
    "supplier_performance",
    # TODO(confirm): the remaining business tables to reach 16 (e.g. demand?). Add here.
})

# Schemas a table is allowed to live in. Anything else (pg_catalog, information_schema,
# pg_temp, a user schema) is rejected outright, before the name is even considered.
ALLOWED_SCHEMAS = frozenset({"public"})

# Functions that stay dangerous even inside a READ ONLY transaction: filesystem/network
# exfiltration and denial-of-service. The table allowlist cannot catch these because they
# are function calls, not table references. This denylist is defense-in-depth BEYOND the
# five named layers — small, explicit, and easy to extend.
DENIED_FUNCTIONS = frozenset({
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file",
    "lo_import", "lo_export", "copy",
    "dblink", "dblink_exec",
    "pg_sleep", "pg_sleep_for", "pg_sleep_until",
    "set_config", "pg_terminate_backend", "pg_cancel_backend",
})


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating one candidate SQL string.

    ok=True  -> `safe_sql` is the validated, LIMIT-enforced SQL to execute.
    ok=False -> `reason` explains the rejection (surfaced in the refusal); safe_sql is None.
    """
    ok: bool
    safe_sql: Optional[str] = None
    reason: Optional[str] = None
    referenced_tables: tuple[str, ...] = ()
    layer: Optional[str] = None  # which layer rejected it, for logging/telemetry


def _reject(layer: str, reason: str) -> ValidationResult:
    return ValidationResult(ok=False, reason=reason, layer=layer)


# ---------------------------------------------------------------------------
# The validator
# ---------------------------------------------------------------------------

def validate_sql(
    sql: str,
    allowed_tables: frozenset[str] = BUSINESS_TABLES,
    max_limit: int = MAX_LIMIT,
) -> ValidationResult:
    """Validate one LLM-drafted SQL string through Layers 2-4.

    Returns a ValidationResult. The caller executes `safe_sql` ONLY when `ok` is True,
    and refuses (INSUFFICIENT_EVIDENCE) with `reason` otherwise.
    """
    if sql is None or not sql.strip():
        return _reject("L2", "empty query")

    # --- Layer 2: parse to exactly one statement -------------------------------------
    try:
        statements = [s for s in sqlglot.parse(sql, dialect=DIALECT) if s is not None]
    except Exception as exc:  # ParseError, TokenError, ...
        return _reject("L2", f"could not parse SQL ({type(exc).__name__})")

    if len(statements) == 0:
        return _reject("L2", "no statement found")
    if len(statements) > 1:
        # Stacked / chained statements (classic injection). A regex on ';' would both
        # miss comment-hidden chaining and false-trigger on ';' inside a string; the
        # parser gets both right.
        return _reject("L2", f"only one statement is allowed; found {len(statements)}")

    stmt = statements[0]

    # --- Layer 2: that one statement must be a plain SELECT --------------------------
    if not isinstance(stmt, exp.Select):
        # Every write (DROP/DELETE/UPDATE/INSERT/TRUNCATE/ALTER/...) and set operations
        # (UNION/INTERSECT/EXCEPT) land here. UNION is rejected conservatively: it is a
        # read, but it is an easy way to append an out-of-allowlist branch, and the
        # analytical use-cases don't need it. Documented restriction, not an oversight.
        return _reject("L2", f"only a single SELECT is allowed (got {type(stmt).__name__})")

    # SELECT ... INTO is a write (it creates a table). sqlglot keeps it as a Select with
    # an `into` arg, so it must be rejected explicitly.
    if stmt.args.get("into") is not None:
        return _reject("L2", "SELECT ... INTO is not allowed (it writes a new table)")

    # --- Layer 3: table / schema / catalog allowlist ---------------------------------
    # CTE names are internal aliases, not real tables. Collect them to skip — but the
    # real tables *inside* each CTE body are still visited by find_all below.
    cte_names = {c.alias_or_name.lower() for c in stmt.find_all(exp.CTE)}

    referenced: list[str] = []
    for tbl in stmt.find_all(exp.Table):
        name = (tbl.name or "").lower()
        schema = (tbl.db or "").lower()        # schema qualifier, e.g. pg_catalog
        catalog = (tbl.catalog or "").lower()  # cross-database qualifier

        # Cross-database access is never legitimate here.
        if catalog:
            return _reject("L3", f"cross-database reference not allowed ('{catalog}.{schema}.{name}')")

        # A bare reference to a CTE name (no schema) is internal — skip it.
        if not schema and name in cte_names:
            continue

        # Explicit schema must be allowlisted. This is the pg_catalog / information_schema
        # / system-table block, independent of the name check below.
        if schema and schema not in ALLOWED_SCHEMAS:
            return _reject("L3", f"schema '{schema}' is not allowed (table '{name}')")

        # The table name itself must be a business table.
        if name not in allowed_tables:
            return _reject("L3", f"table '{name}' is not in the allowlist")

        referenced.append(name)

    # --- Layer 3 (defense-in-depth): dangerous function denylist ---------------------
    for fn in stmt.find_all(exp.Anonymous):
        fn_name = (fn.name or "").lower()
        if fn_name in DENIED_FUNCTIONS:
            return _reject("L3", f"function '{fn_name}()' is not allowed")
    # Some dangerous builtins have dedicated nodes rather than Anonymous; catch by name.
    for fn in stmt.find_all(exp.Func):
        fn_name = (getattr(fn, "name", "") or "").lower()
        if fn_name in DENIED_FUNCTIONS:
            return _reject("L3", f"function '{fn_name}()' is not allowed")

    # --- Layer 4: force a LIMIT (preserve a smaller one, cap a larger/absent one) -----
    stmt = _enforce_limit(stmt, max_limit)

    safe_sql = stmt.sql(dialect=DIALECT)
    return ValidationResult(
        ok=True,
        safe_sql=safe_sql,
        referenced_tables=tuple(dict.fromkeys(referenced)),  # de-duped, order-preserved
        layer=None,
    )


def _enforce_limit(stmt: exp.Select, max_limit: int) -> exp.Select:
    """Guarantee an outer LIMIT <= max_limit, preserving a smaller existing LIMIT."""
    limit_node = stmt.args.get("limit")
    if limit_node is None:
        return stmt.limit(max_limit)

    value_expr = limit_node.expression
    # Literal integer limit: keep if already within the cap, otherwise lower it.
    if isinstance(value_expr, exp.Literal) and value_expr.is_int:
        if int(value_expr.name) > max_limit:
            return stmt.limit(max_limit)
        return stmt  # smaller user limit preserved as-is
    # Non-literal / weird limit expression: replace with the hard cap to be safe.
    return stmt.limit(max_limit)
