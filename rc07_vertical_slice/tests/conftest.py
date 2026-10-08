from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


import pytest

# Tests must not depend on the ambient environment. The Docker stack sets USE_QDRANT,
# QDRANT_URL etc. on the app container; without this, tests that expect the JSON/local
# default silently talk to the live Qdrant server instead.
_AMBIENT = ("USE_QDRANT", "QDRANT_URL", "QDRANT_PATH", "USE_DOC_SUMMARY", "OLLAMA_HOST",
            "OLLAMA_MODEL", "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD",
            "DATABASE_URL", "DOCUMENT_ROOT")


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch):
    for name in _AMBIENT:
        monkeypatch.delenv(name, raising=False)
