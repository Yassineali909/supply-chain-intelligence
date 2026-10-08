"""Regression lock: the Ollama embedder must honor OLLAMA_HOST (Docker stack).
The seed container hit ConnectionRefused because the default host was hardcoded
to localhost. This pins the env-driven behavior, hermetically (no network)."""
import sys, os, urllib.request
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qdrant_store import _default_ollama_host, make_ollama_embedder


def test_default_host_is_localhost_when_env_unset(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert _default_ollama_host() == "http://localhost:11434"


def test_default_host_follows_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama:11434")
    assert _default_ollama_host() == "http://ollama:11434"


def test_embedder_rest_call_targets_env_host(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama:11434")
    monkeypatch.setitem(sys.modules, "ollama", None)   # force the REST fallback path
    seen = {}

    def fake_urlopen(req):
        seen["url"] = req.full_url
        raise RuntimeError("stop-after-capture")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    embed = make_ollama_embedder("nomic-embed-text")    # no host passed, like build_qdrant_index
    with pytest.raises(RuntimeError):
        embed(["probe"])
    assert seen["url"] == "http://ollama:11434/api/embeddings"
