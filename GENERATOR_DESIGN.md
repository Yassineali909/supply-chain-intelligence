# DETERMINISTIC EVENT GENERATOR — DESIGN

**Part of:** Supply Chain Intelligence Platform (see `PROJECT_KNOWLEDGE.md` v0.3.0)
**This document:** how the synthetic-data generator is structured, in what order it
produces events, how the causal levers bias the data, and how it enforces the two
forward-pointed rules (evidence floor, ground-truth artifact). Skeleton code lives in
`datagen/` (stubs + signatures + docstrings; no logic yet).

The generator is the piece that makes or breaks the whole project. If it produces
correlated, testable data, every later layer has something real to work on. If the
correlations are subtly broken, every later metric is measuring noise. So this design
optimizes for **one thing above all: a downstream consumer can trust that the data
matches the ground truth.**

---

## 0. Non-negotiables (inherited from the knowledge base)

1. **PostgreSQL is the source of truth.** The generator writes structured rows first;
   everything else (graph, documents, embeddings) is a projection built *after*.
2. **The generator does NOT embed.** It writes documents as plain records + metadata.
   A separate `indexing/` step (not covered here) pushes them to Qdrant. This keeps
   generation deterministic and lets you re-embed or swap stores without regenerating.
3. **One seed drives everything.** Same seed → byte-identical structured output and
   byte-identical factual skeletons. (LLM prose is the *only* non-deterministic part,
   and it is validated + regenerable, never a source of truth.)
4. **The answer key is separate.** `ground_truth/scenarios.json` and `context_for`
   associations are written by the generator but never enter queryable metadata.
5. **Evidence floor is enforced at generation time**, not discovered at eval time.

---

## 1. Why generation ORDER is the load-bearing decision

Correlation is created by *when* you decide each fact, using facts already decided.
If you generate shipments before applying the port-congestion lever, the lever can't
bias them. If you generate documents before incidents exist, they can't cite incident
codes. The entire correctness of the dataset is a topological sort of dependencies.

**The mandatory order (each stage may only read stages above it):**

```
STAGE 0  Seed + config resolution
STAGE 1  Reference / master data
         product_categories → products
         suppliers (+ hidden reliability_tier lever)
         customers
         carriers (+ hidden perf_trend lever)
         ports    (+ hidden congestion_season lever)
         warehouses (+ capacity_units ceiling)
         routes (bind port + warehouse)
         supplier_contracts (agreed_lead_days per supplier)
STAGE 2  Demand model
         monthly demand curve over 24 months (+ seasonal peak)
STAGE 3  Purchase orders
         drawn from demand; promised_date = order_date + contract lead
STAGE 4  Shipments   ← THE CAUSAL HEART
         assign route + carrier + mode; compute planned dates;
         compute actual dates by applying ALL relevant levers (§3)
STAGE 5  Deliveries  ← where the WAREHOUSE lever acts (downstream of shipment)
         planned vs actual; WH capacity slip applied here, NOT at shipment
STAGE 6  Invoices    (from PO + shipment; disputes link to incidents later)
STAGE 7  Incidents   ← materialize the "why" for delays the levers produced
         seeded incidents carry root_cause_id; background incidents do not
STAGE 8  supplier_performance rollup (pure aggregation of stages 4–7)
STAGE 9  Graph projection (Neo4j) — derived from PostgreSQL only
STAGE 10 Document skeletons (factual) — from stages 1–7
STAGE 11 Document prose (LLM) + validation — §4
STAGE 12 Manifest + ground-truth artifacts + evidence-floor check — §5
```

**Critical ordering subtleties (these are the bugs waiting to happen):**

- **RC-04 must act at STAGE 5, not STAGE 4.** The warehouse-capacity delay is
  *downstream*: inbound shipment arrives on time (stage 4), outbound delivery slips
  (stage 5). If you apply it at stage 4 you destroy the whole point of RC-04 (the
  agent is supposed to localize the delay to the warehouse stage, not the supplier).
- **Incidents (stage 7) are generated AFTER the delays they explain (stage 4–5).**
  You don't roll a dice for incidents and then make delays match; you observe the
  delays the levers produced and write incidents that explain the seeded ones. This
  guarantees the incident always corresponds to a real delay.
- **RC-06's "unexplained" delays are produced at stage 4 but deliberately get NO
  seeded incident at stage 7 and NO direct document at stage 10.** They still get
  *contextual* documents (docs about the same supplier/route/period that already exist
  for other reasons). The trap is emergent, not manufactured.
- **supplier_performance (stage 8) is pure derivation.** It must be reproducible by a
  single SQL query over stages 4–7. If it isn't, it's wrong. (It exists only for
  convenience/speed; never as an independent fact.)

---

## 2. Module structure (`datagen/`)

Flat and legible, matching the GDPR project's style (single config, module-level
docstrings that explain *why*). Each generator module owns one stage and is
independently testable.

```
datagen/
├── __init__.py
├── config.py               # every tunable knob: counts, seed, lever strengths, floors
├── seed.py                 # deterministic RNG handling (one root seed → child streams)
├── run.py                  # orchestrator: runs stages 0–12 in order; CLI (--no-llm, --seed)
│
├── model.py                # dataclasses for every entity + document record (typed)
│
├── stage1_reference.py     # master data + LEVER INJECTION (hidden columns)
├── stage2_demand.py        # 24-month demand curve with seasonal peak
├── stage3_orders.py        # purchase_orders + order_items
├── stage4_shipments.py     # shipments + APPLY LEVERS to actual dates   ← causal heart
├── stage5_deliveries.py    # deliveries + warehouse-capacity slip (RC-04)
├── stage6_invoices.py      # invoices
├── stage7_incidents.py     # incidents; seeded (root_cause_id) vs background
├── stage8_performance.py   # supplier_performance rollup (aggregation only)
│
├── levers.py               # ALL causal-lever logic in one place (§3) — auditable
├── scenarios.py            # the 7 RC definitions as data; drives seeding + answer key
│
├── graph_projection.py     # STAGE 9: build Neo4j from PostgreSQL rows
│
├── docs/
│   ├── skeletons.py        # STAGE 10: factual skeletons from structured rows
│   ├── prose.py            # STAGE 11: LLM rewrite (Ollama) OR --no-llm passthrough
│   └── validate.py         # STAGE 11: assert required codes present, foreign absent
│
├── writers/
│   ├── postgres_writer.py  # STAGE 1–8 → PostgreSQL (the source of truth)
│   ├── document_writer.py  # STAGE 10–11 → plain doc records (NOT embedded)
│   ├── manifest.py         # STAGE 12: generation_manifest.json + per-scenario counts
│   └── ground_truth.py     # STAGE 12: ground_truth/scenarios.json + context_for
│
└── checks/
    └── evidence_floor.py   # STAGE 12: assert each SUPPORTED scenario meets its floor
```

**Why `levers.py` and `scenarios.py` are separate and central:** an interviewer will
ask "how did you make sure the data actually contains the problems you claim?" The
answer is "every causal mechanism lives in two auditable files: `scenarios.py` declares
what should be true, `levers.py` makes it true, and `checks/evidence_floor.py` proves
it happened." That is the defensible story.

---

## 3. How the causal levers work (`levers.py`)

A lever is a deterministic bias applied to an event's outcome, driven by a hidden
column decided in stage 1. Levers are **additive and independent** so their effects
can be disentangled by the evaluator (this is what makes RC-02's de-confounding real).

Each lever answers: given a shipment/delivery and the entities it touches, how many
extra delay-days does this mechanism contribute?

```
delay_days(shipment) =
      base_noise(rng)                         # small symmetric noise, always present
    + supplier_lever(supplier)                # RC-02: problematic suppliers run late
    + port_congestion_lever(route, date)      # RC-01: PORT-GEN in Q1
    + carrier_lever(carrier, date)            # RC-03: CR3 degrades over time
    # NOTE: warehouse_lever is applied to DELIVERY, not shipment (RC-04, stage 5)
```

**Design rules that keep the levers honest:**

- **Levers are monotonic and documented.** `supplier_lever` returns 0 for reliable
  suppliers, a positive mean for problematic ones. No hidden interactions.
- **RC-02 de-confounding is enforced structurally, not hoped for.** `stage4_shipments`
  must assign S07 a controlled mix of PORT-GEN and clean routes, with a configurable
  minimum count on clean routes (`config.RC02_MIN_CLEAN_ROUTE_SHIPMENTS`). The port
  lever contributes 0 on clean routes, so S07's residual delay there is *purely* the
  supplier lever — which is exactly the signal the agent must find. If this minimum
  isn't met, the evidence-floor check fails the build.
- **RC-01 and RC-05 share one mechanism.** The port lever *is* RC-01; RC-05 is the same
  events viewed as a network. There is no separate "RC-05 lever" — the generator just
  ensures S07/S11/S19/S23 all have enough RT-04 shipments and *partially overlapping*
  customer sets (`scenarios.py` declares the overlap; `stage3/4` realize it).
- **RC-03 is time-dependent.** `carrier_lever(CR3, date)` scales with months-elapsed, so
  early shipments are clean and late ones are worst. The evaluator checks a *trend*, not
  a level — which is why RC-03's expected outcome is 🟡 when asked for a single cause.
- **RC-06 is the absence of a lever, plus presence of context.** The generator picks a
  few delayed shipments (their delay comes from base_noise or a since-resolved cause),
  assigns them **no seeded incident and no direct document**, but ensures contextual
  docs about their supplier/route/period already exist. Recorded in the answer key via
  `context_for`, never in queryable metadata.

---

## 4. Document generation (`docs/`)

Three sub-steps, matching the knowledge base's structured→skeleton→prose→validate.

**`skeletons.py` (STAGE 10, deterministic).** For each document to create, pull the
exact facts it must contain from structured rows. A skeleton is a typed dict of
locked facts — no prose. This is the deterministic backbone; the same seed produces
the same skeletons regardless of whether the LLM runs.

**`prose.py` (STAGE 11, non-deterministic but constrained).** Rewrite a skeleton into
natural text via Ollama, with the hard-constraint prompt (use only these facts, invent
no codes/dates/numbers). `--no-llm` skips this and emits terse text from the skeleton
directly, so the pipeline runs without Ollama (CI, fallback). Prose is regenerable and
never a source of truth.

**`validate.py` (STAGE 11, deterministic gate).** For each generated document:
- assert every required code/date/number from the skeleton appears in the text;
- assert no *foreign* codes appear (regex for the code patterns `S\d+`, `SH-\d+`,
  `INC-\d+`, `PO-\d+`, etc. that don't belong to this skeleton);
- on failure, regenerate up to N tries, then fall back to skeleton text and log it.

The validator is what lets you trust LLM prose without trusting the LLM. It is also a
genuine engineering talking point: "the LLM writes the words, but a deterministic
validator guarantees the facts."

---

## 5. The three STAGE-12 artifacts (this is where the forward-pointers get answered)

**`writers/manifest.py` → `artifacts/generation_manifest.json`.** Records
`generator_version`, `seed`, wall-clock, total counts, and **per-scenario incident and
document counts** (RC-01…RC-07 + BACKGROUND). Per-scenario counts are mandatory: when a
scenario later fails to be answerable, the first question is "did enough evidence get
generated?" and this file answers it without a manual query.

**`writers/ground_truth.py` → `artifacts/ground_truth/scenarios.json`.** The serialized
answer key. Per scenario: expected_outcome, affected_entities, evidence
(sql_signatures, direct_causal_document_ids, context_document_ids), expected_paths (for
graph scenarios), reasoning_requirements, direct_cause_evidence_required, and the
evaluator-only `context_for` map. Written from the same deterministic model, kept
outside the queryable database.

**`checks/evidence_floor.py` → the build gate (answers forward-pointer #1).** After
generation, assert each scenario meets a declared minimum. This turns "did enough
evidence get generated?" from an eval-time surprise into a generation-time failure.

```python
# Per-scenario floors declared in scenarios.py, e.g.:
#   RC-01: >= 6 corroborating docs, >= 20 affected shipments
#   RC-02: >= RC02_MIN_CLEAN_ROUTE_SHIPMENTS clean-route S07 shipments,
#          >= 8 S07 docs, contract doc present
#   RC-04: >= 4 corroborating warehouse docs, inbound-normal/outbound-late invariant holds
#   RC-05: 4 suppliers on RT-04, customer-overlap count in declared range
#   RC-06: >= 2 context docs, EXACTLY 0 direct-causal docs, 0 seeded incidents
#   RC-07: exactly 1 explanatory incident + 1 doc
# If any floor is unmet, the generator EXITS NON-ZERO. A weak dataset never ships.
```

**Forward-pointer #2 (evidence-trace contract) is explicitly NOT solved here** — it's
an agent-output-contract decision that belongs in Section 11. The generator only needs
to provide the answer key against which a trace will later be scored; it does.

---

## 6. Determinism strategy (`seed.py`)

One root seed (`config.SEED`) spawns **named child streams**, one per stage, so adding
a later stage doesn't shift the random draws of earlier ones. (A single shared RNG
would mean any change to stage 4 changes stage 7's output — brittle.)

```python
root = seed_everything(config.SEED)
rng_suppliers = child_stream(root, "suppliers")
rng_shipments = child_stream(root, "shipments")
# ...independent, reproducible, stage-isolated
```

A determinism test (open question #3 in the KB) regenerates twice and asserts identical
row counts + a checksum over the structured tables + identical `scenarios.json`. Prose
is excluded from the checksum (it's the one non-deterministic projection).

---

## 7. What this design deliberately does NOT do

- **No embedding / no Qdrant calls.** Separate `indexing/` step. (Qdrant is settled as
  the store, but the generator stays store-agnostic by writing plain records.)
- **No agent, no eval logic.** The generator produces the exam and the answer key; the
  evaluator (Section 14) is separate and reads both.
- **No 10–20 scenarios.** Seven, floor-checked, beat fifteen half-generated ones. Add
  more only after these run end-to-end.
- **No cloud, no Docker here.** Generation is a local, deterministic batch job.

---

## 8. Suggested build order for the generator itself

1. `model.py` + `config.py` + `seed.py` — the types and determinism spine.
2. Stages 1–3 + `postgres_writer` — get master data and orders into Postgres, eyeball it.
3. Stage 4 + `levers.py` — the causal heart; verify delay distributions by hand.
4. Stages 5–8 — deliveries (RC-04!), invoices, incidents, rollup.
5. `scenarios.py` + `checks/evidence_floor.py` — make the floors real; let them fail first.
6. Stages 10–11 docs + `validate.py` — skeletons, then prose, then the validator.
7. Stage 9 graph projection — last, since it's a pure re-read of Postgres.
8. Stage 12 manifest + ground truth — wire the artifacts; run the determinism test.

Build stage 4 + levers *before* documents. The temptation is to make text early
because it's satisfying; resist it. If the structured correlations are wrong, pretty
documents just hide the bug.
```