"""
Streamlit UI for the Supply Chain Intelligence agent.

Type a question -> the agent investigates across SQL / documents / graph -> the UI shows
the tool-call trace, the verified answer, the evidence it is bound to, and the
verification checks. A view over the AgentResponse the agent already produces; no agent
logic lives here.

Run:  streamlit run app.py
(requires Postgres, Neo4j, Ollama, and the generated data all running)
"""
from __future__ import annotations

import streamlit as st

from router import investigate
from ollama_llm import ollama_call

import os
_RAW_DB = os.environ.get("DATABASE_URL", "postgresql://yassine:devpass@localhost:5432/meridian")
# app uses the psycopg3 SQLAlchemy driver prefix; normalize whatever form the env gives.
DB = _RAW_DB.replace("postgresql+psycopg://", "postgresql://", 1).replace("postgresql://", "postgresql+psycopg://", 1)
DOCS = os.environ.get("DOCUMENT_ROOT", "../artifacts/documents")

OUTCOME_BADGE = {
    "SUPPORTED": ("🟢", "Supported"),
    "PARTIALLY_SUPPORTED": ("🟡", "Partially supported"),
    "INSUFFICIENT_EVIDENCE": ("🔴", "Insufficient evidence"),
}
TOOL_ICON = {
    "query_database": "🗄️",
    "search_documents": "📄",
    "graph_query": "🕸️",
    "verify_evidence": "✅",
}

st.set_page_config(page_title="Supply Chain Intelligence", page_icon="🔎", layout="wide")
st.title("🔎 Supply Chain Intelligence")
st.caption("An agent that investigates across SQL, documents, and a graph - and shows its work. "
           "Every claim is bound to evidence a tool produced, or the answer is downgraded.")

with st.sidebar:
    st.header("Try a question")
    st.write("**Shipment** - what happened to SH-6968?")
    st.write("**Supplier** - why is supplier S07 chronically late?")
    st.write("**Impact (graph)** - which customers are affected by congestion at the port through shared routes?")
    st.write("**Out of scope** - what is the capital of France?")
    st.divider()
    st.caption("Requires Postgres, Neo4j, Ollama + generated data running.")

question = st.text_input("Ask a supply-chain question",
                         placeholder="e.g. Why is supplier S07 chronically late?")

if st.button("Investigate", type="primary") and question:
    with st.status("Investigating...", expanded=True) as status:
        st.write("Routing the question and running the investigation...")
        try:
            resp = investigate(ollama_call, DB, DOCS, question)
        except Exception as e:
            status.update(label="Error", state="error")
            st.error(f"Investigation failed: {e}")
            st.stop()
        status.update(label="Done", state="complete")

    icon, label = OUTCOME_BADGE.get(resp.outcome.value, ("⚪", resp.outcome.value))

    c1, c2 = st.columns([3, 1])
    with c1:
        st.subheader(f"{icon} {label}")
    with c2:
        st.metric("Verification", resp.verification.status)

    st.markdown("#### Investigation trace")
    if resp.tool_trace:
        for t in resp.tool_trace:
            ti = TOOL_ICON.get(t.tool, "•")
            state = "✓" if t.status == "SUCCESS" else "✗"
            st.markdown(f"**{ti} {t.tool}** {state} - {t.purpose}")
    else:
        st.write("_No tools called (out of scope)._")

    st.markdown("#### Answer")
    st.write(resp.answer)

    if resp.evidence:
        st.markdown("#### Evidence")
        for e in resp.evidence:
            with st.expander(f"[{e.evidence_id}] {e.source_type.value} · {e.relevance.value}"):
                st.write(e.fact)
                st.caption(f"source: {e.source_ref}")

    if resp.claims:
        st.markdown("#### Claims & verification")
        for cl in resp.claims:
            st.markdown(f"- **{cl.claim_type.value}** ({cl.support_status.value}) - {cl.text}  "
                        f"`→ {', '.join(cl.evidence_ids)}`")
        st.markdown("**Checks:**")
        for chk in resp.verification.checks:
            mark = "✅" if chk.status == "PASS" else "❌"
            st.markdown(f"{mark} `{chk.type}`")
