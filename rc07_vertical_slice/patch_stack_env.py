def patch(path, edits):
    src = open(path, encoding="utf-8").read()
    for name, old, new in edits:
        if new in src:
            print(f"  [{path}] {name}: already present, skipping"); continue
        n = src.count(old)
        assert n == 1, f"[{path}] {name}: anchor matched {n}x (expected 1) -- aborting"
        src = src.replace(old, new)
        print(f"  [{path}] {name}: patched")
    bad = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
    assert not bad, f"[{path}] non-ASCII at {bad[:3]} -- aborting"
    open(path, "w", encoding="utf-8").write(src)

# 1. document_retrieval: open the Qdrant SERVER when QDRANT_URL is set
patch("document_retrieval.py", [
    ("url-or-index guard",
     '    if not Path(_QDRANT_PATH).exists():\n'
     '        _warn_once(f"USE_QDRANT=1 but no index at {_QDRANT_PATH}")\n'
     '        return None',
     '    url = os.environ.get("QDRANT_URL")\n'
     '    if url is None and not Path(_QDRANT_PATH).exists():\n'
     '        _warn_once(f"USE_QDRANT=1 but no index at {_QDRANT_PATH}")\n'
     '        return None'),
    ("url construction",
     '        _store = QdrantDocumentStore.on_disk(_QDRANT_PATH, embed, vector_size=dim)',
     '        if url:\n'
     '            _store = QdrantDocumentStore.on_url(url, embed, vector_size=dim)\n'
     '        else:\n'
     '            _store = QdrantDocumentStore.on_disk(_QDRANT_PATH, embed, vector_size=dim)'),
])

# 2. run_logger: DB from env + create the runs table lazily (nothing else creates it in the stack)
patch("run_logger.py", [
    ("LOG_DB env",
     'LOG_DB = "postgresql://yassine:devpass@localhost:5432/meridian"',
     'import os as _os\n'
     'LOG_DB = _os.environ.get("DATABASE_URL", "postgresql://yassine:devpass@localhost:5432/meridian")'
     '.replace("postgresql+psycopg://", "postgresql://", 1)\n'
     '_STATE = {"schema_ready": False}'),
    ("lazy schema",
     '        total_ms = getattr(getattr(response, "timing", None), "total_ms", None)\n'
     '        conn = psycopg2.connect(db_url)',
     '        total_ms = getattr(getattr(response, "timing", None), "total_ms", None)\n'
     '        if not _STATE["schema_ready"]:\n'
     '            ensure_schema(db_url)\n'
     '            _STATE["schema_ready"] = True\n'
     '        conn = psycopg2.connect(db_url)'),
])
print("done")
