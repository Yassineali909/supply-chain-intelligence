"""
Run logging for observability. Every agent investigation writes one row to a Postgres
`runs` table: what was asked, how it was routed, the outcome, whether verification
passed, latency, and the tool sequence. This run history feeds metrics + Grafana.

Logging is best-effort and MUST NOT break an investigation: any logging error is
swallowed (the agent's job is to answer; logging is secondary).
"""
from __future__ import annotations

from datetime import datetime, timezone

import psycopg2

import os as _os
LOG_DB = _os.environ.get("DATABASE_URL", "postgresql://yassine:devpass@localhost:5432/meridian").replace("postgresql+psycopg://", "postgresql://", 1)
_STATE = {"schema_ready": False}

RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    log_id        BIGSERIAL PRIMARY KEY,
    run_id        TEXT,
    ts            TIMESTAMPTZ NOT NULL,
    question      TEXT,
    route_type    TEXT,
    outcome       TEXT,
    verification  TEXT,
    n_tools       INT,
    tool_sequence TEXT,
    n_claims      INT,
    total_ms      INT
);
"""


def ensure_schema(db_url: str = LOG_DB) -> None:
    conn = psycopg2.connect(db_url)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(RUNS_SCHEMA)
    finally:
        conn.close()


def log_run(response, route_type: str, db_url: str = LOG_DB) -> None:
    """Write one AgentResponse to the runs table. Best-effort; never raises."""
    try:
        tools = [t.tool for t in response.tool_trace]
        total_ms = getattr(getattr(response, "timing", None), "total_ms", None)
        if not _STATE["schema_ready"]:
            ensure_schema(db_url)
            _STATE["schema_ready"] = True
        conn = psycopg2.connect(db_url)
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO runs (run_id, ts, question, route_type, outcome,
                           verification, n_tools, tool_sequence, n_claims, total_ms)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (response.run_id, datetime.now(timezone.utc), response.question,
                     route_type, response.outcome.value, response.verification.status,
                     len(tools), ">".join(tools), len(response.claims), total_ms),
                )
        finally:
            conn.close()
    except Exception as e:
        print(f"[run_logger] warning: failed to log run ({e})")
