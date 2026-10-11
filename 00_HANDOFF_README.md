# PROJECT HANDOFF — Supply Chain Intelligence Platform

**Purpose of this folder:** This project is built across long conversations. This handoff
lets a fresh conversation (a "virgin" Claude with no memory of the work) pick up exactly
where things stand — what was built, why, what decisions were made, what bugs were hit and
how they were fixed, and what to do next.

**If you are the next Claude reading this: start with this file, then read the other three
in order. Treat these as authoritative context. The user (Yassine) works with high rigor —
match it. Text-to-SQL AND a Qdrant vector store with semantic search are now BUILT and LIVE
(this was the previous session's work). The next build is open — see file 03.**

---

## The four handoff files

1. **00_HANDOFF_README.md** (this file) — overview, identity, the big picture.
2. **01_ARCHITECTURE_AND_STATE.md** — the full technical architecture, every component,
   file layout, and exactly what is built vs. not.
3. **02_DECISIONS_AND_BUGS.md** — every significant design decision (and the reasoning),
   plus every real bug hit and how it was fixed. The "hard-won lessons" file.
4. **03_START_HERE_NEXT_SESSION.md** — how to bring the environment up, the exact state,
   the prioritized next steps. **START THERE after this file** — step 1 is confirming state.

---

## Who the user is (carried forward)

**Yassine Ali** — final-year Industrial IT Engineering student (ENET'Com, Sfax, Tunisia),
AI + Embedded Systems. Based in Manouba, Tunisia. Working on WSL (Ubuntu) + VS Code,
Python 3.14.

**Why this project exists:** It is his SECOND portfolio project. The first was a
production-grade GDPR RAG assistant. This second project demonstrates a DIFFERENT, more
advanced skill cluster: **agentic AI + multi-source fusion (SQL + graph + vector) +
structured/unstructured integration + rigorous evaluation + observability.** It is a CV
centerpiece. Target roles: AI/LLM Engineer, GenAI Engineer, ML Engineer — RegTech,
logistics, enterprise AI.

**How he works (match this):** verify against real data before trusting a layer; prove the
red (mutation testing) not just the green; measure, don't assert; refuse rather than
overclaim; watch `git status` for strays; commit per coherent unit; **never green-wash a
board** — a passing test count can hide a real gap (this bit us twice in the last session —
see file 02). When something is "done," confirm it from a clean clone, not just locally.

---

## What the project IS (one paragraph)

An **agentic AI platform** that investigates operational supply-chain problems — "what
happened to this shipment?", "why is this supplier chronically late?", "which customers
does a port disruption cascade to?", "is this carrier degrading?", "which supplier is the
worst?", **"how many shipments used carrier CR3?", "average delay per carrier?", "what do
our documents say about customs holds?"** — by autonomously routing the question and
investigating across **three data sources (SQL, documents/vectors, graph)**, then returning
**verified, source-cited answers** and **refusing to guess** when evidence is insufficient.
It runs fully locally/free via Ollama. Distinguishing features: a deterministic
synthetic-data generator with **planted, separable, hidden-lever ground truth**; the **LLM
plans but deterministic code controls the evidence** (Option A); a **mutation-tested
verifier** gating every claim; a **safety-first text-to-SQL path** (the LLM writes SQL,
layered deterministic guardrails keep it safe); a **Qdrant vector store** with exact lookup
(RC-06-preserving) and **semantic search**; a **self-validating evaluation harness**; and
both a **Streamlit UI** and a **Grafana dashboard**.

---

## The fictional company

**MeridianFreight Distribution S.A.** (DB name `meridian`) — a mid-sized international
freight distributor. Goods move: **Supplier → Port → Warehouse → Customer**. ~30 suppliers,
~60 customers, ~120 products, 4 warehouses, 5 ports, 6 carriers, 12 routes, 3000 purchase
orders, 3000 shipments, 3000 deliveries, ~2746 incident/operational docs, 24 months with a
seasonal demand peak (June/July).

---

## Capabilities (the core idea) — ALL LIVE

The generator plants seven known root-cause stories with **hidden causal levers** (columns
that bias the data but are STRIPPED from the schema the agent sees, so the agent must
investigate, not look up the answer). Plus capabilities built beyond the 7 scenarios.

| ID | Story | Capability | Outcome | Claim type | Source |
|----|-------|-----------|---------|-----------|--------|
| RC-01 | Port congestion at PORT-GEN in Q1 | seasonal pattern | SUPPORTED | COMPARATIVE | SQL |
| RC-02 | Supplier S07 chronically late | de-confounding supplier vs route | SUPPORTED | COMPARATIVE | SQL |
| RC-03 | Carrier CR3 degrading over time | trend vs single-cause | PARTIALLY_SUPPORTED | TREND | SQL |
| RC-04 | Warehouse WH-2 capacity bottleneck | stage localization (a TRAP) | SUPPORTED | COMPARATIVE | SQL |
| RC-05 | Shared-route co-exposure (S07/S11/S19/S23 on RT-04) | multi-hop graph | SUPPORTED | RELATIONSHIP | graph |
| RC-06 | Unexplained delay (no explanatory doc) | honest refusal | INSUFFICIENT_EVIDENCE | NUMERIC only | SQL+docs |
| RC-07 | Isolated customs hold on one shipment | precise single-entity retrieval | SUPPORTED | NUMERIC+CAUSAL | SQL+docs |

Beyond the 7 scenarios (all LIVE):
- **Supplier ranking** ("which supplier is the worst?") — de-confounded clean-route delay. COMPARATIVE. SQL.
- **TEXT-TO-SQL / analytical route** — open-ended aggregate/count questions the scenarios
  don't cover ("how many shipments used CR3?" → 473; "average delay per carrier?"). The LLM
  WRITES SQL; layered guardrails validate; read-only execution; **AGGREGATE** claim type,
  verified per value. Scalar AND grouped (GROUP BY) results. SQL.
- **Semantic document search / doc_search route** — "what do our documents say about X?".
  Qdrant vector search; Option-A RAG (retrieve + deterministic report, NO LLM synthesis);
  RELATIONSHIP claim; refuses below a measured similarity floor. Vectors.

Every contract claim type (COMPARATIVE, TREND, RELATIONSHIP, NUMERIC, CAUSAL, AGGREGATE) is
exercised by at least one live investigation.

---

## Current status in one line

A working multi-source agentic platform: generator + Postgres + Neo4j + documents + **Qdrant
vectors** + verified agent (**7 scenarios + ranking + text-to-SQL + semantic search**) +
self-validating eval (**dev 14 Q + held-out 11 Q, both 100%**) + Streamlit UI + Grafana.
**156 automated tests, all passing, verified green from a clean clone. Everything committed
and pushed to GitHub.**

GitHub: `https://github.com/Yassineali909/supply-chain-intelligence`

**NEXT BUILD: open** — strong candidates in file 03 (grounded-LLM-summary for doc_search with
its own hallucination verifier; Docker Compose; demo video; semantic search in the UI).

---

## The guiding discipline (how this project was built — KEEP THIS)

1. **Test the deterministic layer before the stochastic one sits on it.**
2. **Prove the red, not just the green** — mutation testing.
3. **Make wrong actions structurally impossible**, don't hope the model behaves (guardrails,
   refuse rather than default, read-only at the DB level).
4. **Verify the data, don't trust that it worked** (counts, distributions, actual numbers,
   ground-truth checks).
5. **Be honest** — "strongly indicates" not "proves"; document limitations; refuse when
   evidence is insufficient; surface residual risk rather than hide it.
6. **Vertical-slice rule:** no new feature unless a failing case needs it.
7. **Safe patching:** small independent edits; scripted multi-edit patches assert each anchor
   matches EXACTLY ONCE and the replacement is NOT already present; apply in-memory, write
   only if all pass. Patch scripts live in the repo (patch_*.py).
8. **The eval drives the work.** The held-out set found the wrong-entity bug, motivated the
   ranking feature, caught the CR3 phrasing miss, and caught an uncalibrated semantic floor.
9. **Measure, don't guess** — thresholds (e.g. the semantic floor) are set from measured
   distributions on the real corpus, then regression-locked with a test.
10. **Never green-wash.** Confirm "done" against a clean clone and the real test count, not
    just a local green board. (See B17/B18/B19 in file 02 — this caught real gaps.)

This discipline is the actual skill on display. KEEP IT — especially its honesty.
