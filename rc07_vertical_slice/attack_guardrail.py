"""
attack_guardrail.py — adversarial proof that the guardrail REJECTS what it should and
PASSES what it should, before any LLM is ever involved. (Mutation-testing's cousin.)

Run: python attack_guardrail.py   (from inside rc07_vertical_slice/)
"""
import sys
from sql_guardrail import validate_sql, MAX_LIMIT

# (label, sql, expect_ok, substring_that_must_appear_in_safe_sql_or_reason)
CASES = [
    # ---- MUST REJECT: destructive writes (threat #1) ----
    ("DROP",            "DROP TABLE shipments",                                 False, "SELECT"),
    ("DELETE",          "DELETE FROM shipments WHERE 1=1",                      False, "SELECT"),
    ("UPDATE",          "UPDATE shipments SET delay_days = 0",                  False, "SELECT"),
    ("INSERT",          "INSERT INTO shipments VALUES (1)",                     False, "SELECT"),
    ("TRUNCATE",        "TRUNCATE shipments",                                   False, "SELECT"),
    ("ALTER",           "ALTER TABLE shipments ADD COLUMN x int",              False, "SELECT"),
    ("SELECT-INTO",     "SELECT * INTO evil FROM shipments",                    False, "INTO"),
    # ---- MUST REJECT: stacked / injection (threat #3) ----
    ("STACKED-DROP",    "SELECT 1; DROP TABLE shipments",                       False, "one statement"),
    ("STACKED-DELETE",  "SELECT * FROM shipments WHERE id=1; DELETE FROM invoices", False, "one statement"),
    ("COMMENT-HIDDEN",  "SELECT * FROM shipments WHERE id=1; DROP TABLE shipments --", False, "one statement"),
    # ---- MUST REJECT: schema escape / exfiltration (threat #2) ----
    ("PG-CATALOG",      "SELECT * FROM pg_catalog.pg_tables",                   False, "pg_catalog"),
    ("INFO-SCHEMA",     "SELECT * FROM information_schema.columns",             False, "information_schema"),
    ("CROSS-DB",        "SELECT * FROM otherdb.public.shipments",               False, "cross-database"),
    ("PG-CATALOG-CTE",  "WITH e AS (SELECT * FROM pg_catalog.pg_user) SELECT * FROM e", False, "pg_catalog"),
    ("SUBQUERY-ESCAPE", "SELECT * FROM (SELECT * FROM pg_catalog.pg_tables) t", False, "pg_catalog"),
    ("READ-FILE-FN",    "SELECT pg_read_file('/etc/passwd')",                   False, "pg_read_file"),
    ("SLEEP-DOS",       "SELECT pg_sleep(60)",                                  False, "pg_sleep"),
    # ---- MUST REJECT: hallucinated / set-op (threats #5, misc) ----
    ("NONEXISTENT",     "SELECT * FROM made_up_table",                          False, "allowlist"),
    ("UNION-ESCAPE",    "SELECT * FROM shipments UNION SELECT * FROM pg_catalog.pg_tables", False, "single SELECT"),
    ("GARBAGE",         "SELCT FRM WHERE",                                      False, "parse"),

    # ---- MUST PASS: benign analytical queries, LIMIT enforced (threat #4) ----
    ("NO-LIMIT-CAP",    "SELECT * FROM shipments",                              True,  f"LIMIT {MAX_LIMIT}"),
    ("COUNT",           "SELECT COUNT(*) FROM shipments WHERE status = 'delayed'", True, f"LIMIT {MAX_LIMIT}"),
    ("GROUP-BY-AVG",    "SELECT carrier_id, AVG(delay_days) FROM shipments GROUP BY carrier_id", True, f"LIMIT {MAX_LIMIT}"),
    ("JOIN-SMALL-LIMIT","SELECT * FROM shipments s JOIN routes r ON s.route_id=r.route_id LIMIT 50", True, "LIMIT 50"),
    ("OVER-CAP-LOWERED","SELECT * FROM shipments LIMIT 100000",                 True,  f"LIMIT {MAX_LIMIT}"),
    ("CTE-OK",          "WITH recent AS (SELECT * FROM shipments WHERE delay_days > 5) "
                        "SELECT carrier_id, COUNT(*) FROM recent GROUP BY carrier_id", True, "recent"),
    ("SEMICOLON-IN-STR","SELECT * FROM shipments WHERE status = 'a; DROP TABLE x'", True, "DROP TABLE x"),
]


def main() -> int:
    width = max(len(c[0]) for c in CASES)
    failures = 0
    print(f"{'CASE'.ljust(width)}  EXPECT  GOT     RESULT")
    print("-" * (width + 32))
    for label, sql, expect_ok, needle in CASES:
        res = validate_sql(sql)
        got_ok = res.ok
        haystack = (res.safe_sql or res.reason or "")
        ok_match = (got_ok == expect_ok)
        needle_match = needle.lower() in haystack.lower()
        passed = ok_match and needle_match
        failures += (0 if passed else 1)
        exp_s = "PASS" if expect_ok else "BLOCK"
        got_s = "PASS" if got_ok else "BLOCK"
        verdict = "ok" if passed else "*** FAIL ***"
        print(f"{label.ljust(width)}  {exp_s:6} {got_s:6}  {verdict}")
        if not passed:
            print(f"    expected needle {needle!r} in -> {haystack!r}")
    print("-" * (width + 32))
    total = len(CASES)
    print(f"{total - failures}/{total} cases behaved correctly "
          f"({sum(1 for c in CASES if not c[2])} block, {sum(1 for c in CASES if c[2])} pass)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
