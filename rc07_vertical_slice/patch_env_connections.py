import re, sys

SMART = re.compile(r'[\u2013\u2014\u2018\u2019\u201c\u201d\u2026]')

def patch(path, edits, *, allow_emoji=False):
    src = open(path, encoding="utf-8").read()
    for name, old, new in edits:
        if new in src:
            print(f"  [{path}] {name}: already present, skipping"); continue
        n = src.count(old)
        assert n == 1, f"[{path}] {name}: anchor matched {n}x (expected 1) -- aborting"
        src = src.replace(old, new)
        print(f"  [{path}] {name}: patched")
    if allow_emoji:
        m = SMART.search(src)
        assert not m, f"[{path}] smart-punctuation at {m.start()} -- aborting"
    else:
        bad = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
        assert not bad, f"[{path}] non-ASCII at {bad[:3]} -- aborting"
    open(path, "w", encoding="utf-8").write(src)

# --- ollama_llm.py: host + model from env ---
patch("ollama_llm.py", [
    ("host+model env",
     'OLLAMA_URL = "http://localhost:11434/api/chat"\nMODEL = "llama3.2:3b"',
     'import os\n'
     '_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")\n'
     'OLLAMA_URL = _OLLAMA_HOST.rstrip("/") + "/api/chat"\n'
     'MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")'),
])

# --- graph_tool.py: neo4j connection from env ---
patch("graph_tool.py", [
    ("neo4j env",
     'NEO4J_URI = "bolt://localhost:7687"\n'
     'NEO4J_USER = "neo4j"\n'
     'NEO4J_PASSWORD = "devpass123"',
     'import os\n'
     'NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")\n'
     'NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")\n'
     'NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "devpass123")'),
])

# --- app.py: DB + DOCS from env (emoji in this file are legitimate data) ---
patch("app.py", [
    ("db+docs env",
     'DB = "postgresql+psycopg://yassine:devpass@localhost:5432/meridian"\n'
     'DOCS = "../artifacts/documents"',
     'import os\n'
     '_RAW_DB = os.environ.get("DATABASE_URL", "postgresql://yassine:devpass@localhost:5432/meridian")\n'
     '# app uses the psycopg3 SQLAlchemy driver prefix; normalize whatever form the env gives.\n'
     'DB = _RAW_DB.replace("postgresql+psycopg://", "postgresql://", 1).replace("postgresql://", "postgresql+psycopg://", 1)\n'
     'DOCS = os.environ.get("DOCUMENT_ROOT", "../artifacts/documents")'),
], allow_emoji=True)

print("done")
