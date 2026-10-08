import sys

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

# 1. qdrant_store.py: add on_url factory next to on_disk
qs_old = ("    @classmethod\n"
          "    def on_disk(cls, path: str, embed_fn: EmbedFn, vector_size: int, collection: str = \"documents\"):\n"
          "        return cls(QdrantClient(path=path), embed_fn, vector_size, collection)")
qs_new = (qs_old + "\n\n"
          "    @classmethod\n"
          "    def on_url(cls, url: str, embed_fn: EmbedFn, vector_size: int, collection: str = \"documents\"):\n"
          "        # Qdrant SERVER mode (Docker stack): a shared daemon multiple containers can reach.\n"
          "        return cls(QdrantClient(url=url), embed_fn, vector_size, collection)")
patch("qdrant_store.py", [("on_url factory", qs_old, qs_new)])

# 2. semantic.py _default_store: prefer QDRANT_URL (server) when set, else on-disk (default)
sem_old = ("    path = os.environ.get(\"QDRANT_PATH\", \"./qdrant_data\")\n"
           "    if not Path(path).exists():\n"
           "        return None\n"
           "    try:\n"
           "        from qdrant_store import QdrantDocumentStore, make_ollama_embedder\n"
           "        embed = make_ollama_embedder(os.environ.get(\"QDRANT_EMBED_MODEL\", \"nomic-embed-text\"))\n"
           "        dim = len(embed([\"dimension probe\"])[0])\n"
           "        return QdrantDocumentStore.on_disk(path, embed, vector_size=dim)\n"
           "    except Exception:\n"
           "        return None")
sem_new = ("    url = os.environ.get(\"QDRANT_URL\")\n"
           "    path = os.environ.get(\"QDRANT_PATH\", \"./qdrant_data\")\n"
           "    if url is None and not Path(path).exists():\n"
           "        return None\n"
           "    try:\n"
           "        from qdrant_store import QdrantDocumentStore, make_ollama_embedder\n"
           "        host = os.environ.get(\"OLLAMA_HOST\", \"http://localhost:11434\")\n"
           "        embed = make_ollama_embedder(os.environ.get(\"QDRANT_EMBED_MODEL\", \"nomic-embed-text\"), host=host)\n"
           "        dim = len(embed([\"dimension probe\"])[0])\n"
           "        if url:\n"
           "            return QdrantDocumentStore.on_url(url, embed, vector_size=dim)\n"
           "        return QdrantDocumentStore.on_disk(path, embed, vector_size=dim)\n"
           "    except Exception:\n"
           "        return None")
patch("semantic.py", [("default_store url mode", sem_old, sem_new)])

# 3. build_qdrant_index.py: write to the server when QDRANT_URL is set (seed must match reader)
bi_old = 'QDRANT_PATH = "./qdrant_data"'
bi_new = ('QDRANT_PATH = "./qdrant_data"\n'
          'import os as _os\n'
          'QDRANT_URL = _os.environ.get("QDRANT_URL")  # set in the Docker stack -> index into the server')
patch("build_qdrant_index.py", [("url const", bi_old, bi_new)])

print("done -- now inspect build_qdrant_index.py where it CONSTRUCTS the store (manual step below)")
