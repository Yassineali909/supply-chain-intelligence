"""Regression locks for the Docker-stack env switches (document_retrieval + run_logger).
Hermetic: no Qdrant server, no Postgres."""
import sys, os, importlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import document_retrieval as dr


def test_get_store_uses_server_when_qdrant_url_set(monkeypatch):
    import qdrant_store
    calls = {}
    monkeypatch.setattr(dr, "_store", None)
    monkeypatch.setattr(dr, "_QDRANT_PATH", "/nonexistent-index")   # no on-disk index
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setattr(qdrant_store, "make_ollama_embedder",
                        lambda model: (lambda texts: [[0.0] * 4 for _ in texts]))
    monkeypatch.setattr(qdrant_store.QdrantDocumentStore, "on_url",
                        classmethod(lambda cls, url, embed, vector_size, collection="documents":
                                    calls.update(url=url) or "SERVER-STORE"))
    assert dr._get_store() == "SERVER-STORE"
    assert calls["url"] == "http://qdrant:6333"


def test_get_store_still_none_without_url_or_index(monkeypatch):
    monkeypatch.setattr(dr, "_store", None)
    monkeypatch.setattr(dr, "_warned", True)          # silence the one-shot stderr warning
    monkeypatch.setattr(dr, "_QDRANT_PATH", "/nonexistent-index")
    monkeypatch.delenv("QDRANT_URL", raising=False)
    assert dr._get_store() is None


def test_run_logger_db_comes_from_env_and_normalizes_driver(monkeypatch):
    import run_logger
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@postgres:5432/meridian")
    try:
        importlib.reload(run_logger)
        assert run_logger.LOG_DB == "postgresql://u:p@postgres:5432/meridian"
    finally:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        importlib.reload(run_logger)                  # restore the localhost default
