"""
Tests for the document_retrieval backend switch. Hermetic — no Qdrant/Ollama needed; the
Qdrant path is exercised via a fake store so only the ROUTING + fallback logic is tested.
"""
import document_retrieval as dr


def _reset(monkeypatch):
    monkeypatch.setattr(dr, "_store", None)
    monkeypatch.setattr(dr, "_warned", False)


def test_default_uses_json_store(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.delenv("USE_QDRANT", raising=False)
    monkeypatch.setattr(dr, "_json_search",
                        lambda *a, **k: (["JSON"], {"tool_call_id": "T"}, k.get("evidence_id")))
    docs, _, _ = dr.search_documents("root", "SH-1")
    assert docs == ["JSON"]


def test_qdrant_requested_but_no_index_falls_back_to_json(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("USE_QDRANT", "1")
    monkeypatch.setattr(dr, "_QDRANT_PATH", "/nonexistent/qdrant_data")
    monkeypatch.setattr(dr, "_json_search",
                        lambda *a, **k: (["JSON-FALLBACK"], {}, "EVD-002"))
    docs, _, _ = dr.search_documents("root", "SH-1")
    assert docs == ["JSON-FALLBACK"]          # safe fallback, no crash
    assert dr._store is None


def test_qdrant_used_when_store_available(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("USE_QDRANT", "1")

    class FakeStore:
        def search_documents(self, code, *, evidence_id, trace_call_id):
            return (["QDRANT"], {"tool_call_id": trace_call_id, "via": "qdrant"}, evidence_id)

    monkeypatch.setattr(dr, "_get_store", lambda: FakeStore())
    docs, trace, eid = dr.search_documents("root", "SH-1",
                                           evidence_id="EVD-X", trace_call_id="TC-X")
    assert docs == ["QDRANT"]
    assert trace["via"] == "qdrant" and eid == "EVD-X"
