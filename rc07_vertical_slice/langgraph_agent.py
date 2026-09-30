"""Optional LangGraph adapter.

The domain logic stays in rc07.py so framework/API changes are isolated here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


class RC07State(TypedDict, total=False):
    shipment_code: str
    database_url: str
    document_root: str
    response: dict


def build_rc07_graph():
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph is not installed. Run `pip install -r requirements.txt`."
        ) from exc

    from rc07 import investigate_rc07

    def investigate(state: RC07State) -> RC07State:
        response = investigate_rc07(
            database_url=state["database_url"],
            document_root=state["document_root"],
            shipment_code=state.get("shipment_code", "SH-4921"),
        )
        return {"response": response.model_dump(mode="json")}

    graph = StateGraph(RC07State)
    graph.add_node("investigate", investigate)
    graph.add_edge(START, "investigate")
    graph.add_edge("investigate", END)
    return graph.compile()
