P = "qdrant_store.py"
src = open(P, encoding="utf-8").read()

edits = [
  ("helper",
   r'_SHIPMENT_CODE_RE = re.compile(r"\bSH-\d+\b")',
   r'_SHIPMENT_CODE_RE = re.compile(r"\bSH-\d+\b")' + "\n\n\n"
   "def _default_ollama_host() -> str:\n"
   "    import os\n"
   '    return os.environ.get("OLLAMA_HOST", "http://localhost:11434")'),
  ("signature",
   'host: str = "http://localhost:11434") -> EmbedFn:',
   'host: str = None) -> EmbedFn:'),
  ("rest url",
   'f"{host}/api/embeddings",',
   'f"{(host or _default_ollama_host()).rstrip(\'/\')}/api/embeddings",'),
]
for name, old, new in edits:
    if new in src:
        print(f"  {name}: already present, skipping"); continue
    n = src.count(old)
    assert n == 1, f"{name}: anchor matched {n}x (expected 1) -- aborting"
    src = src.replace(old, new)
    print(f"  {name}: patched")
bad = [(i, c) for i, c in enumerate(src) if ord(c) >= 128]
assert not bad, f"non-ASCII at {bad[:3]} -- aborting"
open(P, "w", encoding="utf-8").write(src)
print("done")
