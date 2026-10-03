"""
Adversarial + behavioral tests for the text-to-SQL guardrail (Layers 2-4).

Hermetic: pure validation, no Postgres / Ollama. These prove the guard REJECTS every
threat category before the LLM is trusted, and PASSES benign analytical queries with the
LIMIT correctly enforced. Mirrors attack_guardrail.py but as assertions.
"""
import pytest

from sql_guardrail import validate_sql, MAX_LIMIT


# --- MUST BLOCK: (label, sql, reason_substring) -----------------------------------------
BLOCK_CASES = [
    # destructive writes (threat #1)
    ("drop",            "DROP TABLE shipments",                                 "select"),
    ("delete",          "DELETE FROM shipments WHERE 1=1",                      "select"),
    ("update",          "UPDATE shipments SET delay_days = 0",                  "select"),
    ("insert",          "INSERT INTO shipments VALUES (1)",                     "select"),
    ("truncate",        "TRUNCATE shipments",                                   "select"),
    ("alter",           "ALTER TABLE shipments ADD COLUMN x int",              "select"),
    ("select_into",     "SELECT * INTO evil FROM shipments",                    "into"),
    # stacked / injection (threat #3)
    ("stacked_drop",    "SELECT 1; DROP TABLE shipments",                       "one statement"),
    ("stacked_delete",  "SELECT * FROM shipments WHERE id=1; DELETE FROM invoices", "one statement"),
    ("comment_hidden",  "SELECT * FROM shipments WHERE id=1; DROP TABLE shipments --", "one statement"),
    # schema escape / exfiltration (threat #2)
    ("pg_catalog",      "SELECT * FROM pg_catalog.pg_tables",                   "pg_catalog"),
    ("info_schema",     "SELECT * FROM information_schema.columns",             "information_schema"),
    ("cross_db",        "SELECT * FROM otherdb.public.shipments",               "cross-database"),
    ("pg_catalog_cte",  "WITH e AS (SELECT * FROM pg_catalog.pg_user) SELECT * FROM e", "pg_catalog"),
    ("subquery_escape", "SELECT * FROM (SELECT * FROM pg_catalog.pg_tables) t", "pg_catalog"),
    ("read_file_fn",    "SELECT pg_read_file('/etc/passwd')",                   "pg_read_file"),
    ("sleep_dos",       "SELECT pg_sleep(60)",                                  "pg_sleep"),
    # hallucinated schema / set-op (threat #5, misc)
    ("nonexistent",     "SELECT * FROM made_up_table",                          "allowlist"),
    ("union_escape",    "SELECT * FROM shipments UNION SELECT * FROM pg_catalog.pg_tables", "single select"),
    ("garbage",         "SELCT FRM WHERE",                                      "parse"),
    ("empty",           "   ",                                                  "empty"),
]

# --- MUST PASS: (label, sql, needle_in_safe_sql) ----------------------------------------
PASS_CASES = [
    ("no_limit_capped",  "SELECT * FROM shipments",                             f"LIMIT {MAX_LIMIT}"),
    ("count",            "SELECT COUNT(*) FROM shipments WHERE status = 'delayed'", f"LIMIT {MAX_LIMIT}"),
    ("group_by_avg",     "SELECT carrier_id, AVG(delay_days) FROM shipments GROUP BY carrier_id", f"LIMIT {MAX_LIMIT}"),
    ("small_limit_kept", "SELECT * FROM shipments s JOIN routes r ON s.route_id=r.route_id LIMIT 50", "LIMIT 50"),
    ("over_cap_lowered", "SELECT * FROM shipments LIMIT 100000",                f"LIMIT {MAX_LIMIT}"),
    ("cte_ok",           "WITH recent AS (SELECT * FROM shipments WHERE delay_days > 5) "
                         "SELECT carrier_id, COUNT(*) FROM recent GROUP BY carrier_id", "recent"),
    ("semicolon_in_str", "SELECT * FROM shipments WHERE status = 'a; DROP TABLE x'", "DROP TABLE x"),
]


@pytest.mark.parametrize("label,sql,needle", BLOCK_CASES, ids=[c[0] for c in BLOCK_CASES])
def test_guardrail_blocks(label, sql, needle):
    res = validate_sql(sql)
    assert res.ok is False, f"{label}: expected BLOCK but it passed -> {res.safe_sql!r}"
    assert res.safe_sql is None
    assert res.reason is not None
    assert needle.lower() in res.reason.lower(), (
        f"{label}: reason {res.reason!r} missing {needle!r}")


@pytest.mark.parametrize("label,sql,needle", PASS_CASES, ids=[c[0] for c in PASS_CASES])
def test_guardrail_passes(label, sql, needle):
    res = validate_sql(sql)
    assert res.ok is True, f"{label}: expected PASS but it was blocked -> {res.reason!r}"
    assert res.safe_sql is not None
    assert needle.lower() in res.safe_sql.lower(), (
        f"{label}: safe_sql {res.safe_sql!r} missing {needle!r}")


# --- targeted behavioral assertions -----------------------------------------------------

def test_smaller_limit_is_preserved_exactly():
    res = validate_sql("SELECT * FROM shipments LIMIT 50")
    assert res.ok
    assert "LIMIT 50" in res.safe_sql
    assert str(MAX_LIMIT) not in res.safe_sql  # not bumped up to the cap


def test_over_cap_limit_is_lowered_to_cap():
    res = validate_sql("SELECT * FROM shipments LIMIT 100000")
    assert res.ok
    assert f"LIMIT {MAX_LIMIT}" in res.safe_sql
    assert "100000" not in res.safe_sql


def test_referenced_tables_are_reported_and_deduped():
    res = validate_sql(
        "SELECT * FROM shipments s JOIN routes r ON s.route_id = r.route_id "
        "WHERE s.route_id IN (SELECT route_id FROM shipments)")
    assert res.ok
    assert set(res.referenced_tables) == {"shipments", "routes"}


def test_rejection_records_the_layer():
    assert validate_sql("DROP TABLE shipments").layer == "L2"
    assert validate_sql("SELECT * FROM pg_catalog.pg_tables").layer == "L3"
    assert validate_sql("SELECT * FROM made_up_table").layer == "L3"


def test_cte_name_is_not_mistaken_for_a_forbidden_table():
    # `recent` is a CTE name, not a real table; must not trip the allowlist.
    res = validate_sql(
        "WITH recent AS (SELECT * FROM shipments) SELECT COUNT(*) FROM recent")
    assert res.ok
    assert "recent" not in res.referenced_tables  # internal name, not a business table
    assert res.referenced_tables == ("shipments",)
