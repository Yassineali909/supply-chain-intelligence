#!/usr/bin/env bash
# One-shot seeding: generate data -> Postgres, project -> Neo4j, embed -> Qdrant server.
# Idempotent: a marker row in Postgres means "already seeded", so re-running up is safe.
set -euo pipefail

ALREADY=$(python - <<'PY'
import os, psycopg2
url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
try:
    c = psycopg2.connect(url); cur = c.cursor()
    cur.execute("SELECT to_regclass('public._seed_marker')")
    print("yes" if cur.fetchone()[0] else "no"); c.close()
except Exception:
    print("no")
PY
)

if [ "$ALREADY" = "yes" ]; then
  echo "[seed] marker found -> already seeded, skipping (drop table _seed_marker to force)"
  exit 0
fi

echo "[seed] 1/3 generating dataset -> Postgres (+docs)"
cd /app
python -m datagen.run --persist --docs

echo "[seed] 2/3 projecting graph -> Neo4j"
python -c "from datagen.run import generate; from datagen.graph_projection import project_graph; project_graph(generate())"

echo "[seed] 3/3 embedding docs -> Qdrant server (QDRANT_URL=$QDRANT_URL)"
cd /app/rc07_vertical_slice
python build_qdrant_index.py

echo "[seed] writing marker"
python - <<'PY'
import os, psycopg2
url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
c = psycopg2.connect(url); cur = c.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS _seed_marker (done_at timestamptz default now())")
cur.execute("INSERT INTO _seed_marker DEFAULT VALUES"); c.commit(); c.close()
print("[seed] marker written -- seeding complete")
PY
