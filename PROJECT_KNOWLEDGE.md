# SUPPLY CHAIN INTELLIGENCE — PROJECT KNOWLEDGE BASE

**Project:** Agentic Supply Chain & Logistics Intelligence Platform
**Document version:** 0.3.0
**Author:** Yassine Ali
**Purpose of this file:** Attach to a Claude Project's knowledge base. It is the
authoritative foundation for the whole build. Sections 2–10 define the fictional
company, correlated data model, and first benchmark question set. **Everything downstream — the 15 investigation
questions, the agent tools, the text-to-SQL layer, the evaluation/ablation harness,
and the demo — must derive from the model defined here.** If a later decision
contradicts this file, this file wins until it is explicitly revised.

> **Status:** Sections 2–10 complete (this document). Sections 11–16 (agent
> architecture, text-to-SQL, verification, evaluation, roadmap, tech decisions) are
> drafted separately after the investigation set is accepted.

---

## SETTLED DECISIONS (do not relitigate without reason)

| Decision | Value | Why |
|---|---|---|
| Scale | Medium: ~30 suppliers, ~3,000 orders | Realistic enough to sound serious, small enough that a wrong number is debuggable by opening the table |
| Domain | Freight / distribution (supplier → port → warehouse → customer) | Richest *multi-hop* structure → genuine Neo4j justification; leverages regulated-goods background; legible incident vocabulary |
| Data generation | Structured events **first** → factual skeleton → LLM prose → validation | Documents stay linguistically varied (real retrieval test) but factually locked to the DB (real ground truth) |
| Neo4j scope | Only genuine multi-hop / shared-network questions | Most questions are SQL `GROUP BY`; graph earns its place only on variable-depth traversal |
| Reproducibility | Single deterministic seed drives the entire generator | Regenerate identical data on any machine; eval is stable |
| LLM fallback | `--no-llm` emits the factual skeleton as plain text | Pipeline runs even if Ollama is down; CI-friendly |
| Ground truth | Seeded root-cause chains are explicit, enumerated, machine-readable | They ARE the evaluation answer key |

---

## SECTION 1 — WHO I AM (carried from prior project)

Yassine Ali — Final-year Industrial IT Engineering student at ENET'Com (Sfax,
Tunisia). AI + Embedded Systems. Based in Manouba, Tunisia.

**Relevant prior project:** A production-grade RAG compliance assistant over GDPR
(structure-aware chunking, hybrid retrieval BM25+dense, cross-encoder reranking,
source-grounded citations, out-of-scope refusal, local LLM-as-judge eval). Key
lessons that carry into THIS project: correlated data matters, measure don't claim,
build the failure/refusal path as a first-class outcome, hold out a fresh test set.

**Why this second project:** Demonstrate a *different* competency cluster than
GDPR (which showed RAG + eval): namely **agentic tool-use + multi-source fusion +
structured/unstructured integration**. Deliberately NOT tied to the industrial-
maintenance PFE, to show range.

---

## SECTION 2 — PROJECT VISION

**One-sentence definition:**

> An AI agent that **investigates** operational supply-chain problems by autonomously
> querying structured business data, searching operational documents, and traversing
> entity relationships, then produces **evidence-backed, verified answers** — and
> refuses to guess when the evidence is insufficient.

The operative word is **investigate**, not **answer**. The contrast:

```
NOT this:                          THIS:
Question                           User question
   ↓                                   ↓
LLM                                Agent forms an objective
   ↓                                   ↓
one DB query                       plans → picks a tool → observes result
   ↓                                   ↓
answer                             decides next tool → gathers evidence
                                       ↓
                                   checks consistency → verifies
                                       ↓
                                   Supported / Partial / Insufficient  + citations
```

**What "verified" means concretely (the project's spine):**
Every numeric claim traces to a SQL result whose query is logged and re-runnable.
Every qualitative claim ("delayed because of port congestion") traces to a retrieved
document. If a claim has no trace, the agent **downgrades its confidence** rather
than asserting it. This is the direct descendant of the GDPR refusal path.

**Three explicit answer outcomes (first-class, not error states):**

- 🟢 **Supported** — structured data + documents agree; claim is fully traceable.
- 🟡 **Partially supported** — some evidence exists; the causal link cannot be confirmed.
- 🔴 **Insufficient evidence** — the system cannot determine the answer from available data and says so.

---

## SECTION 3 — THE FICTIONAL COMPANY

**Name:** **MeridianFreight Distribution S.A.** (internal system name: `meridian`)

**What it does:** A mid-sized international freight distributor. It buys goods from
suppliers abroad, moves them by sea and road through ports and regional warehouses,
and delivers to business customers (B2B) across a handful of countries. It does not
manufacture — it sources, ships, stores, and delivers. (This keeps the project firmly
out of PFE manufacturing territory.)

**Operating footprint (deliberately sized for "medium"):**

| Dimension | Count | Notes |
|---|---|---|
| Suppliers | 30 | Mix of reliable, average, and 3–4 deliberately problematic |
| Products | ~120 | Grouped into ~8 categories (electronics, industrial parts, consumables…) |
| Customers | ~60 | B2B; each has a priority tier (standard / priority / strategic) |
| Warehouses | 4 | Regional distribution centers |
| Ports | 5 | Entry points; one is a deliberate chronic bottleneck |
| Carriers | 6 | Sea + road freight operators; one has degrading performance |
| Routes | ~12 | Named lanes: (origin region → port → warehouse) |
| Purchase Orders | ~3,000 | Spread across ~24 months for seasonality |
| Shipments | ~3,000 | Roughly 1 primary shipment per PO (some consolidated) |
| Deliveries | ~3,000 | Shipment → customer leg |
| Invoices | ~3,000 | One per PO/shipment |
| Incidents | ~250 | Delays, damages, customs holds, congestion, capacity |
| Documents (unstructured) | ~600–900 | Emails, incident reports, port bulletins, contracts, delivery notes |

**Time span:** 24 months of operations ending "recently," so questions like
"this month vs last month" and "Q1 vs Q2" are meaningful. Seasonality is built in
(demand peaks, a congestion season) so trends are real, not noise.

**Design principle:** the company must be realistic enough to *generate interesting
problems on its own* — the interesting questions should fall out of the operational
structure, not be bolted on. That is the difference between "I generated 10,000 fake
rows" and "I designed a synthetic enterprise environment with correlated events,
documents, and relationships, including known causal scenarios for evaluating an
agentic investigation system."

---

## SECTION 4 — BUSINESS PROCESSES (the event model)

Everything the generator produces is an **event** in one of these processes. Getting
the processes right is what makes the data internally consistent.

**Process A — Procurement.**
Customer demand (or replenishment) → **Purchase Order** raised against a **Supplier**
for one or more **Products** (**Order Items**). The PO has an *agreed lead time* from
the supplier's **contract/SLA**.

**Process B — Inbound freight.**
The PO is fulfilled as a **Shipment** assigned a **Route** (origin region → **Port** →
**Warehouse**) and a **Carrier** and a **mode** (sea / road). The shipment has a
*planned departure*, *planned arrival*, and later *actual* dates. Delay = actual −
planned.

**Process C — Port & warehouse handling.**
The shipment clears a **Port** (possible customs hold / congestion) and is received
at a **Warehouse** (possible capacity issue). Each handoff can spawn an **Incident**.

**Process D — Outbound delivery.**
Goods move from **Warehouse** to **Customer** as a **Delivery** with its own planned
vs actual dates. Customer priority tier influences expected service level.

**Process E — Billing.**
Each shipment/PO generates an **Invoice** (amount, due date, paid date, possible
dispute linked to an incident).

**Process F — Exceptions & communication.**
Delays, damages, holds, and disputes generate **Incidents** and the **documents**
(emails, incident reports, port bulletins) that describe them — *written from the
same events*, per Section 8.

**Key causal levers built into the processes (these create the interesting questions):**
- A supplier's *reliability* biases its shipments' delay distribution.
- A port's *congestion season* biases delays for every route through it.
- A carrier's *degradation over time* biases later shipments.
- A warehouse's *capacity ceiling* biases delays during demand peaks.
These levers are what the agent must *discover* — and what the seeded scenarios
(Section 9) make verifiable.

---

## SECTION 5 — ENTITIES & RELATIONSHIPS

### 5.1 Entity list (structured, lives in PostgreSQL)

```
suppliers            customers            products            product_categories
purchase_orders      order_items          shipments           deliveries
routes               ports                warehouses          carriers
invoices             incidents            supplier_contracts  supplier_performance (derived/materialized)
```

### 5.2 Relationship map (the "physical" supply chain)

```
                         supplier_contracts
                                 │ (SLA lead time, penalty terms)
                                 ▼
   Supplier ─────raises────► Purchase Order ──has──► Order Item ──of──► Product ──in──► Category
      │                          │
      │                          └────fulfilled by────► Shipment
      │                                                    │
      │                                                    ├──assigned──► Route ──through──► Port
      │                                                    │                     └──ends at──► Warehouse
      │                                                    ├──carried by──► Carrier
      │                                                    ├──generates──► Invoice
      │                                                    └──may raise──► Incident
      │                                                                       ▲
      ▼                                                                       │
   (performance rolls up from shipment outcomes)                             │
                                                                             │
   Warehouse ──ships to──► Delivery ──to──► Customer ◄───priority tier───────┘
```

### 5.3 Which relationships are SQL vs GRAPH (decide now — this is the Neo4j justification)

**SQL handles (single-table or simple-join, aggregation):**
- supplier → its shipments → delay stats (`GROUP BY supplier`)
- warehouse → its incidents count
- supplier → contract SLA vs actual (SLA breach)
- month-over-month / quarter trends

**GRAPH handles (multi-hop, variable depth, shared intermediate nodes):**
- Customer ⇄ Shipment ⇄ Route ⇄ Port ⇄ *other* Shipments ⇄ *other* Customers
  ("which customers are affected because their shipments share a congested port")
- Supplier ⇄ Route ⇄ Warehouse ⇄ *other* Suppliers on the same lane
  ("which suppliers are exposed to the same disrupted route as Supplier X")
- Reachability / "connected to" questions where the number of hops isn't fixed

**Rule for the whole project:** if a question can be answered by a single `GROUP BY`,
it is a SQL question and must NOT be sent to the graph. Neo4j is reserved for
questions whose *natural expression* is a traversal of shared nodes at variable
depth. In the 15 questions (Section 10), only ~3–4 will be flagged `GRAPH`. Being
able to explain *why the rest are SQL* is itself an interview asset.

---

## SECTION 6 — POSTGRESQL SCHEMA

Column types abbreviated. `PK` primary key, `FK` foreign key. All dates are `DATE`
unless a time matters (`TIMESTAMP`). IDs are human-legible codes (`S07`, `SH-4921`)
stored alongside surrogate integer keys, because the *documents reference the codes*
and the agent's citations should too.

```sql
-- ── Reference / master data ───────────────────────────────────────────────
product_categories(
  category_id      PK,
  name             TEXT,          -- 'Electronics', 'Industrial Parts', ...
)

products(
  product_id       PK,
  sku              TEXT UNIQUE,    -- 'PRD-0142'
  name             TEXT,
  category_id      FK → product_categories,
  unit_cost        NUMERIC
)

suppliers(
  supplier_id      PK,
  code             TEXT UNIQUE,    -- 'S07'  (used in documents & citations)
  name             TEXT,           -- 'Hanwa Components Ltd'
  country          TEXT,
  reliability_tier TEXT,           -- 'reliable' | 'average' | 'problematic'  (ground-truth lever; NOT shown to agent)
  onboarded_on     DATE
)

supplier_contracts(
  contract_id      PK,
  supplier_id      FK → suppliers,
  agreed_lead_days INT,            -- the SLA the agent checks breaches against
  penalty_clause   TEXT,           -- short text; also appears in the contract document
  valid_from       DATE,
  valid_to         DATE
)

customers(
  customer_id      PK,
  code             TEXT UNIQUE,    -- 'C031'
  name             TEXT,
  country          TEXT,
  priority_tier    TEXT            -- 'standard' | 'priority' | 'strategic'
)

carriers(
  carrier_id       PK,
  code             TEXT UNIQUE,    -- 'CR3'
  name             TEXT,
  mode             TEXT,           -- 'sea' | 'road'
  perf_trend       TEXT            -- 'stable' | 'degrading'  (ground-truth lever; hidden)
)

ports(
  port_id          PK,
  code             TEXT UNIQUE,    -- 'PORT-GEN'
  name             TEXT,
  country          TEXT,
  congestion_season TEXT           -- e.g. 'Q1'  (ground-truth lever; hidden)
)

warehouses(
  warehouse_id     PK,
  code             TEXT UNIQUE,    -- 'WH-2'
  name             TEXT,
  region           TEXT,
  capacity_units   INT             -- ceiling that interacts with demand peaks
)

routes(
  route_id         PK,
  code             TEXT UNIQUE,    -- 'RT-04'
  name             TEXT,           -- 'East-Asia → PORT-GEN → WH-2'
  origin_region    TEXT,
  port_id          FK → ports,
  warehouse_id     FK → warehouses,
  planned_transit_days INT
)

-- ── Transactional / event data ────────────────────────────────────────────
purchase_orders(
  po_id            PK,
  po_code          TEXT UNIQUE,    -- 'PO-10432'
  supplier_id      FK → suppliers,
  order_date       DATE,
  promised_date    DATE,           -- order_date + contract agreed_lead_days
  status           TEXT            -- 'open' | 'fulfilled' | 'cancelled'
)

order_items(
  item_id          PK,
  po_id            FK → purchase_orders,
  product_id       FK → products,
  quantity         INT,
  line_amount      NUMERIC
)

shipments(
  shipment_id      PK,
  shipment_code    TEXT UNIQUE,    -- 'SH-4921'  (heavily referenced in documents)
  po_id            FK → purchase_orders,
  route_id         FK → routes,
  carrier_id       FK → carriers,
  mode             TEXT,           -- 'sea' | 'road'
  planned_departure DATE,
  planned_arrival  DATE,
  actual_departure DATE,
  actual_arrival   DATE,           -- NULL if in transit
  delay_days       INT,            -- actual_arrival - planned_arrival (materialized for convenience)
  status           TEXT            -- 'in_transit' | 'arrived' | 'delayed' | 'cancelled'
)

deliveries(
  delivery_id      PK,
  delivery_code    TEXT UNIQUE,    -- 'DL-8830'
  shipment_id      FK → shipments,
  customer_id      FK → customers,
  warehouse_id     FK → warehouses,
  planned_date     DATE,
  actual_date      DATE,
  delay_days       INT,
  status           TEXT
)

invoices(
  invoice_id       PK,
  invoice_code     TEXT UNIQUE,    -- 'INV-22014'
  po_id            FK → purchase_orders,
  amount           NUMERIC,
  issued_date      DATE,
  due_date         DATE,
  paid_date        DATE,           -- NULL if unpaid
  disputed         BOOLEAN,        -- true if linked to an incident
  status           TEXT            -- 'paid' | 'unpaid' | 'disputed'
)

incidents(
  incident_id      PK,
  incident_code    TEXT UNIQUE,    -- 'INC-042'  (referenced in reports & citations)
  incident_type    TEXT,           -- 'delay' | 'customs_hold' | 'port_congestion'
                                   --  | 'damage' | 'capacity_shortfall' | 'carrier_delay'
  severity         TEXT,           -- 'low' | 'medium' | 'high'
  occurred_on      DATE,
  -- polymorphic-ish links: any subset may be set
  shipment_id      FK → shipments   NULL,
  supplier_id      FK → suppliers   NULL,
  port_id          FK → ports       NULL,
  warehouse_id     FK → warehouses  NULL,
  carrier_id       FK → carriers    NULL,
  root_cause_id    TEXT NULL        -- links to a seeded scenario (Section 9); NULL for background noise
)

-- ── Derived / materialized (rebuilt after generation) ─────────────────────
supplier_performance(
  supplier_id      FK → suppliers,
  period_month     DATE,           -- first of month
  orders_count     INT,
  on_time_count    INT,
  avg_delay_days   NUMERIC,
  sla_breach_count INT,
  PRIMARY KEY (supplier_id, period_month)
)
```

**Notes that matter for correctness:**
- `reliability_tier`, `perf_trend`, `congestion_season` are **ground-truth levers**
  the generator uses to bias distributions. They are stored so *you* can verify the
  data, but they are **withheld from the agent's schema view** — otherwise the agent
  cheats by reading the answer instead of investigating. (The text-to-SQL layer gets
  a curated schema that hides these columns.)
- `delay_days` is materialized on `shipments`/`deliveries` for convenient SQL, but the
  generator computes it from dates so it is always consistent.
- `incidents.root_cause_id` is the hook that ties a row to a seeded scenario. Most
  incidents have `NULL` here (background noise); the seeded ones point to Section 9.

---

## SECTION 7 — NEO4J GRAPH MODEL

The graph is a **projection** of the same events — not a second source of truth. It is
built *from* PostgreSQL after generation, so PostgreSQL remains authoritative and Neo4j
can always be rebuilt and checked against it.

**Invariant:** every graph node and relationship must be derivable from PostgreSQL rows.
No graph-only business fact may be created manually.

### 7.1 Node labels

`Supplier`, `PurchaseOrder`, `Shipment`, `Route`, `Port`, `Warehouse`, `Delivery`,
`Customer`, `Carrier`, `Incident`.

`Delivery` is a real domain entity in PostgreSQL and therefore exists explicitly in the
graph. This prevents the graph from silently changing the business model.

### 7.2 Relationships

```text
(Supplier)-[:RAISED]->(PurchaseOrder)
(PurchaseOrder)-[:FULFILLED_BY]->(Shipment)
(Shipment)-[:VIA_ROUTE]->(Route)
(Route)-[:THROUGH_PORT]->(Port)
(Route)-[:ENDS_AT]->(Warehouse)
(Shipment)-[:CARRIED_BY]->(Carrier)
(Shipment)-[:HAS_DELIVERY]->(Delivery)
(Delivery)-[:DELIVERED_TO]->(Customer)
(Incident)-[:AFFECTS]->(Shipment)
(Incident)-[:AFFECTS]->(Port)
(Incident)-[:AFFECTS]->(Warehouse)
(Incident)-[:AFFECTS]->(Carrier)
(Incident)-[:AFFECTS]->(Supplier)
```

For query convenience, Neo4j may additionally materialize:

```text
(Shipment)-[:DELIVERED_TO]->(Customer)
```

but this is a **derived shortcut** over:

```text
Shipment → Delivery → Customer
```

It is never an independent source of truth. The projection builder must be able to
reconstruct or remove the shortcut purely from PostgreSQL.

### 7.3 Why Neo4j exists

**SQL handles** single-table and ordinary-join questions:

- supplier → shipments → delay statistics
- warehouse → incident counts
- supplier → contract SLA vs actual
- month-over-month / quarter trends

**GRAPH handles** shared-network and multi-hop questions:

- Customer ← Shipment → Route → Port ← other Routes/Shipments → other Customers
- Supplier → PurchaseOrder → Shipment → shared Route → other Shipments → other Suppliers
- Supplier → Shipment → Route → Warehouse → Delivery → Customer across a shared network
- reachability / co-exposure / blast-radius questions where traversal structure matters

The RC-05 network is deliberately legible but non-trivial: **S07, S11, S19, and S23**
share RT-04 / PORT-GEN, while their downstream customer sets only partially overlap.
The overlap is generated explicitly so the graph answer cannot be reduced to "return these
four supplier rows."

### 7.4 Example graph traversals

```cypher
// Customers exposed to a congested port through any affected route
MATCH (c:Customer)<-[:DELIVERED_TO]-(d:Delivery)<-[:HAS_DELIVERY]-(s:Shipment)
      -[:VIA_ROUTE]->(:Route)-[:THROUGH_PORT]->(p:Port {code:$port})
RETURN DISTINCT c.code
```

```cypher
// Suppliers sharing a disrupted route with Supplier X
MATCH (x:Supplier {code:$x})-[:RAISED]->(:PurchaseOrder)
      -[:FULFILLED_BY]->(:Shipment)-[:VIA_ROUTE]->(r:Route)
      <-[:VIA_ROUTE]-(:Shipment)<-[:FULFILLED_BY]-(:PurchaseOrder)
      <-[:RAISED]-(other:Supplier)
WHERE other <> x
RETURN DISTINCT other.code, r.code
```

```cypher
// Trace a scenario's downstream customer exposure
MATCH (i:Incident {code:$inc})-[:AFFECTS]->(:Shipment)
      -[:HAS_DELIVERY]->(:Delivery)-[:DELIVERED_TO]->(c:Customer)
RETURN DISTINCT c.code
```

### 7.5 Graph debugging rule

The graph must remain manually inspectable. For seeded graph scenarios, the evaluator
stores expected paths or path signatures in the separate ground-truth artifact. A graph
answer is not considered correct merely because the returned node set "looks plausible";
the returned relationships must correspond to valid PostgreSQL-derived paths.

**Rule:** if a question can be answered by a simple `GROUP BY`, count, average, or
ordinary relational join, it is a SQL question and must not be routed to Neo4j.

## SECTION 8 — DOCUMENT CORPUS (unstructured, lives in the vector store)

Documents are **generated from the structured events**, never independently. This is
the single most important correctness rule in the project.

### 8.1 Document types

| Type | ~Count | Generated from | Key fields it MUST contain |
|---|---|---|---|
| Supplier email | ~250 | shipment / PO events | supplier code, PO/shipment code, dates |
| Incident report | ~250 | one `incidents` row | incident code, type, affected shipment/port, date |
| Port bulletin | ~40 | port congestion periods | port code, congestion window, affected routes |
| Delivery note | ~150 | delivery events | delivery code, shipment code, customer code, date |
| Supplier contract | ~30 | `supplier_contracts` row | supplier code, agreed lead days, penalty clause |
| Warehouse report | ~40 | warehouse capacity events | warehouse code, period, capacity issue |

Total ≈ 600–900 documents. Each document carries **queryable metadata** for metadata-aware
retrieval and for joining back to structured data. Evaluation-only associations that
would reveal the benchmark scenario are kept **out of this metadata** and stored only
in `ground_truth/scenarios.json`.

```json
{
  "doc_id": "DOC-000317",
  "doc_type": "incident_report",
  "supplier_code": "S07",
  "shipment_code": "SH-4921",
  "incident_code": "INC-042",
  "port_code": "PORT-GEN",
  "warehouse_code": null,
  "customer_code": null,
  "date": "2026-02-14",
  "root_cause_id": "RC-01",       // seeded direct-evidence docs only; RC-06 context docs keep null
  "period_quarter": "2026-Q1"
}
```

### 8.2 The generation pipeline (structured → skeleton → prose → validate)

```
1. STRUCTURED EVENTS  (Python, seeded RNG)  ──► PostgreSQL rows (source of truth)
                       │
2. FACTUAL SKELETON    (Python) ── pulls the exact codes/dates/numbers a given
                       │            document must state, from the rows above.
                       │            e.g. {supplier:'S07', shipment:'SH-4921',
                       │                  delay_days:8, cause_hint:'port congestion',
                       │                  incident:'INC-042', date:'2026-02-14'}
                       ▼
3. LLM PROSE           (Ollama) ── rewrites the skeleton into a natural email /
                       │            report. HARD CONSTRAINT in the prompt:
                       │            "Use ONLY these facts. Invent no new codes,
                       │             dates, or numbers."
                       ▼
4. VALIDATION          (Python) ── assert every required code/date/number from the
                       │            skeleton appears in the output; assert no
                       │            foreign shipment/PO/incident codes appear
                       │            (regex for the code patterns). Regenerate on
                       │            failure, up to N tries, else fall back to skeleton text.
                       ▼
5. EMBED + STORE       ──► vector store, with the metadata block from 8.1
```

**Why hybrid and not either extreme:**
- Pure Python/Faker → template prose → retrieval eval is fake (semantic search looks
  better than it is because everything is phrased identically).
- Pure free-form LLM → invents facts → ground truth silently breaks.
- Hybrid with validation → **varied wording, locked facts.** Best of both, and the
  validation step is itself a defensible engineering decision.

**`--no-llm` fallback:** step 3 is skipped and the skeleton is emitted as terse plain
text. The pipeline still runs end-to-end (useful for CI and for machines without
Ollama). Documents are less natural but factually identical, so eval still functions.

### 8.3 Deliberate negatives (for the refusal path)

A subset of delayed shipments are generated with **no corresponding explanatory
document** — the delay exists in the data but nothing explains *why*. These are the
ground truth for the 🔴 **Insufficient evidence** outcome. Without planted negatives,
you cannot test that the agent refuses instead of hallucinating a cause. (Direct
carry-over of the GDPR out-of-scope lesson.)

---

### 8.4 Separate generation artifacts: manifest + ground truth

PostgreSQL is the operational source of truth, but the **evaluation answer key must not
live only inside PostgreSQL**. Generation therefore writes two serialized artifacts:

```text
artifacts/
├── generation_manifest.json
└── ground_truth/
    └── scenarios.json
```

`generation_manifest.json` records reproducibility and coverage statistics:

```json
{
  "generator_version": "0.1.0",
  "seed": 20260929,
  "generated_at": "...",
  "counts": {
    "suppliers": 30,
    "purchase_orders": 3000,
    "shipments": 3000,
    "deliveries": 3000,
    "incidents": 250,
    "documents": 742
  },
  "incident_counts_by_root_cause": {
    "RC-01": 24,
    "RC-02": 31,
    "RC-03": 18,
    "RC-04": 16,
    "RC-05": 12,
    "RC-06": 8,
    "RC-07": 1,
    "BACKGROUND": 140
  },
  "document_counts_by_root_cause": {
    "RC-01": 14,
    "RC-02": 19,
    "RC-03": 8,
    "RC-04": 5,
    "RC-05": 0,
    "RC-06": 0,
    "RC-07": 1,
    "BACKGROUND": 695
  },
  "context_document_counts_by_scenario": {
    "RC-06": 12
  }
}
```

The numbers above are **illustrative schema only**; the generator computes the real
values. Per-scenario counts are mandatory because debugging a weak scenario requires
answering "did enough evidence actually get generated?" without manually querying every
table.

`ground_truth/scenarios.json` is the serialized "exam answer key." For each seeded
scenario it stores:

```json
{
  "root_cause_id": "RC-02",
  "title": "Supplier S07 chronic lateness",
  "expected_outcome": "SUPPORTED",
  "affected_entities": {
    "suppliers": ["S07"],
    "shipments": ["..."],
    "routes_clean_for_control": ["..."]
  },
  "evidence": {
    "sql_signatures": ["..."],
    "document_ids": ["..."],
    "required_comparisons": ["S07 clean-route delay vs peer delay"]
  },
  "expected_paths": [],
  "reasoning_requirements": [
    "do not attribute S07's lateness solely to PORT-GEN exposure",
    "show that S07 remains late on unaffected routes",
    "compare against peers on comparable clean routes"
  ],
  "direct_cause_evidence_required": true
}
```

The artifact is generated **once from the same deterministic event model**, then kept
separate from the database that the agent is allowed to query. This lets the evaluator
re-run against a fixed answer key, rebuild PostgreSQL/Neo4j/vector indexes independently,
and version the benchmark without exposing the answer directly to the agent.

For scenarios with contextual-noise traps, the answer key may also include evaluator-only
associations such as:

```json
{
  "root_cause_id": "RC-06",
  "evidence": {
    "direct_causal_document_ids": [],
    "context_document_ids": ["DOC-000410", "DOC-000521"],
    "context_for": {
      "DOC-000410": "RC-06",
      "DOC-000521": "RC-06"
    }
  }
}
```

`context_for` is answer-key metadata only. It must never reach the agent through document
metadata, retrieval payloads, logs exposed to the model, or the public benchmark prompt.

## SECTION 8.5 — ARCHITECTURE INVARIANT: SOURCE OF TRUTH VS DISPOSABLE PROJECTIONS

The most important architectural rule is:

> **PostgreSQL is the operational source of truth. Neo4j, prose, embeddings, and vector
> indexes are disposable projections. The evaluation answer key is a separate serialized
> artifact.**

The dependency chain is:

```text
                    DETERMINISTIC EVENT GENERATOR
                               │
                  ┌────────────┴────────────┐
                  ▼                         ▼
             PostgreSQL                ground_truth/
            SOURCE OF TRUTH           scenarios.json
                  │                         │
        ┌─────────┴─────────┐               │
        ▼                   ▼               │
     Neo4j              Document Builder     │
   projection                 │             │
                              ▼             │
                         LLM prose          │
                              │             │
                         Validator          │
                              │             │
                              ▼             │
                       Vector Store         │
                              │             │
                              └──────┬──────┘
                                     ▼
                                  Evaluator
```

Rebuild policy:

- Destroy/rebuild Neo4j from PostgreSQL whenever necessary.
- Regenerate prose from the same factual skeletons without changing the structured events.
- Re-embed documents without changing ground truth.
- Re-run evaluation against the versioned ground-truth artifact without regenerating
  the database.
- Never make the benchmark depend on facts that exist only in an LLM-generated document.

### 8.5.1 — FORWARD-POINTERS BEFORE IMPLEMENTATION

Two decisions are intentionally left for implementation design rather than prose-only
resolution:

- The generator must enforce a measurable **evidence floor** for each SUPPORTED scenario
  and record failures in its manifest.
- Section 11 must define a machine-checkable **evidence trace contract** for reasoning-aware
  evaluation (claim → tool result / document / row-set binding), without leaking answer-key
  metadata.

### 8.5.2 — HOW THE REST OF THE PROJECT DERIVES FROM SECTIONS 2–9

- **Section 10 (15 questions):** each question is authored against one or more scenarios,
  tagged `{SQL | RAG | GRAPH | MULTI}`, with expected outcome and source/tool requirements.
- **Section 11 (agent):** tools are exactly `query_database`, `search_documents`,
  `graph_query`, `verify_evidence`. The plan/observe/decide loop is justified by the
  multi-source and graph scenarios.
- **Section 12 (text-to-SQL):** evaluate whether generated SQL returns the expected row
  set / aggregate signature. RC-04 and RC-02 are the hardest cases because they require
  stage localization and controlled comparison, not just entity lookup.
- **Section 13 (verification/refusal):** validate 🟢 / 🟡 / 🔴 against RC-01 / RC-03 / RC-06,
  with explicit direct-evidence rules.
- **Section 14 (evaluation/ablation):** compare increasingly capable configurations and
  determine whether each tool materially improves the answer on the questions that need it.
- **Section 15 (roadmap):** each layer must be independently runnable before the next
  technology is introduced.
- **Section 16 (technology decisions):** choose infrastructure based on contribution to
  the workload, not logo count.

---

## SECTION 9 — SEEDED ROOT-CAUSE SCENARIOS (the evaluation ground truth)

These are the **known causal stories** planted into the data. Because they are planted,
the project knows the correct answer, the expected evidence, and the expected tool class.
The generator stamps the relevant structured rows and document metadata; the evaluator
reads the corresponding records from `artifacts/ground_truth/scenarios.json`.

### 9.1 Scenario record contract

Each scenario is a machine-readable record containing:

```text
root_cause_id
title
lever
affected_entities
time_window
signature_in_SQL
signature_in_DOCS
needs_graph
expected_outcome
expected_evidence
reasoning_requirements
direct_cause_evidence_required
```

The key addition is **`reasoning_requirements`**. For some scenarios, especially RC-02,
an answer can name the correct entity but still be wrong about *why*. The evaluator must
therefore score evidence-backed reasoning, not just final labels.

### 9.2 The planted scenarios

**RC-01 — Port congestion at PORT-GEN during Q1.**
- **Lever:** `ports.congestion_season = 'Q1'` for PORT-GEN.
- **Effect:** shipments on RT-03 and RT-04 receive elevated delay in Jan–Mar.
- **SQL signature:** average delay on routes through PORT-GEN spikes in Q1 versus
  comparable periods.
- **DOCS signature:** port bulletin(s), port-congestion incidents, and supplier emails
  referencing PORT-GEN and the affected dates.
- **needs_graph:** yes for the blast-radius variant ("which customers were affected?").
- **Expected outcome:** 🟢 Supported.
- **Reasoning requirement:** connect the elevated delay to the PORT-GEN Q1 disruption,
  not merely report that delays increased.

**RC-02 — Supplier S07 chronic lateness, deliberately de-confounded from RC-01.**
- **Lever:** `suppliers.reliability_tier = 'problematic'` for S07.
- **Effect:** S07 is consistently late across a **mix of PORT-GEN and non-PORT-GEN
  routes**. Enough S07 volume is generated on clean routes to support a peer comparison.
- **SQL signature:** compare S07's delay on non-PORT-GEN routes against other suppliers
  on comparable clean routes; S07 remains materially worse. SLA breach counts are also high.
- **DOCS signature:** S07 incident reports/emails plus its supplier contract, which states
  the agreed lead time and penalty terms.
- **needs_graph:** no.
- **Expected outcome:** 🟢 Supported.
- **Reasoning requirements:**
  1. Establish that S07 is late.
  2. Demonstrate that the lateness persists on routes not affected by RC-01.
  3. Compare S07 with peers under similar clean-route conditions.
  4. Use documents/contract evidence to corroborate the supplier-specific finding.
  5. Do **not** conclude "S07 is late because PORT-GEN is congested."
- **Evaluation note:** final-answer correctness alone is insufficient. The evaluator must
  inspect whether the required comparison is present in the evidence trace.

**RC-03 — Carrier CR3 degradation over time.**
- **Lever:** `carriers.perf_trend = 'degrading'` for CR3.
- **Effect:** CR3 shipments begin near baseline and worsen across the 24-month period.
- **SQL signature:** CR3 monthly average delay trends upward; recent months are worst.
- **DOCS signature:** later-dated `carrier_delay` incidents naming CR3, with little or no
  corresponding early-period incident evidence.
- **needs_graph:** no.
- **Expected outcome:** 🟢 Supported for "trend"; 🟡 Partially supported if the question
  asks for one definitive root cause.
- **Reasoning requirement:** distinguish an observed performance trend from a proven single
  causal event.

**RC-04 — Warehouse WH-2 capacity shortfall during the demand peak.**
- **Lever:** WH-2 capacity ceiling interacting with the seasonal demand peak.
- **Effect:** inbound shipments arrive near normal, but outbound deliveries from WH-2 slip.
- **SQL signature:** outbound delivery delay at WH-2 spikes during the peak while inbound
  shipment delay for the same goods remains normal.
- **DOCS signature:** warehouse report describing capacity strain for that period.
- **needs_graph:** no.
- **Expected outcome:** 🟢 Supported.
- **Reasoning requirement:** localize the disruption to the warehouse stage rather than
  blaming the upstream supplier.

**RC-05 — Shared-route co-exposure (the graph showcase).**
- **Lever:** RC-01 congestion, viewed as a shared network effect.
- **Effect:** **S07, S11, S19, and S23** all use RT-04 / PORT-GEN, with **partially
  overlapping customer sets** downstream. The overlap is intentional but non-uniform.
- **SQL signature:** weak for the complete question; SQL can identify route membership,
  but the supplier→route→shipment→delivery→customer network must be traversed to derive
  the full exposure set and overlaps.
- **DOCS signature:** RC-01 congestion evidence is reused as corroborating context.
- **needs_graph:** **yes — this is the primary Neo4j justification.**
- **Expected outcome:** 🟢 Supported.
- **Reasoning requirement:** return the network relationship that connects suppliers and
  customers through the disrupted shared route; do not answer from supplier membership alone.

**RC-06 — Unexplained delay with contextual noise (planted negative).**
- **Lever:** none.
- **Effect:** selected shipment(s) are delayed, but there is no direct evidence establishing
  the cause.
- **DOCS signature:** **related context is intentionally present** — documents may mention
  the same supplier, route, or time period and may describe historical problems — but none
  names the target shipment and establishes a causal explanation for its delay.
- **SQL signature:** the delay is real and measurable.
- **needs_graph:** no.
- **Expected outcome:** 🔴 **Insufficient evidence.**
- **Reasoning requirements:**
  1. Acknowledge the observed delay from structured data.
  2. Distinguish contextual documents from direct causal evidence for the target shipment.
  3. Explicitly state that the cause cannot be established from the available evidence.
  4. Do **not** infer causality from route/supplier/period correlation.
- **Generator constraint:** contextual documents must not assert a direct cause for the
  target shipment, and their queryable metadata must not falsely link them to its root cause.
  Their evaluator-only association is recorded separately as `context_for: "RC-06"` in the
  ground-truth artifact.

**RC-07 — Customs hold at PORT-ADR (isolated, single-incident).**
- **Lever:** one specific `customs_hold` incident on a high-value shipment.
- **Effect:** one shipment (e.g. SH-4921) is delayed eight days by a customs hold.
- **SQL signature:** one shipment's delay and one incident row.
- **DOCS signature:** exactly one directly explanatory incident report (e.g. INC-042).
- **needs_graph:** no.
- **Expected outcome:** 🟢 Supported.
- **Reasoning requirement:** retrieve the specific incident and connect its facts to the
  shipment without expanding into unrelated contextual causes.

### 9.3 Coverage check

| Capability | Covered by |
|---|---|
| Single-entity SQL + citation | RC-02, RC-07 |
| Trend / time-series SQL | RC-03, RC-04 |
| Correct-stage localization | RC-04 |
| Controlled comparison / de-confounding | RC-02 |
| Document retrieval + structured fusion | RC-01, RC-02, RC-07 |
| Multi-hop graph traversal | RC-05 (and RC-01 blast-radius) |
| 🔴 Honest refusal under contextual noise | RC-06 |
| 🟡 Partial support | RC-03 |
| 🟢 Full multi-source support | RC-01, RC-02, RC-05 |

Everything downstream — the 15 questions, tool set, evaluator, and demo — derives from
this scenario contract. The separate ground-truth artifact is the answer key; PostgreSQL,
Neo4j, and the vector store are exam surfaces rather than answer keys.

## SECTION 10 — INVESTIGATION QUESTIONS

The questions below are the first benchmark set. They are deliberately written to force
the agent to distinguish lookup, aggregation, retrieval, controlled comparison, graph
traversal, multi-source fusion, and refusal.

### 10.1 SQL-only

**Q01 — Supplier performance**
> Which suppliers had the lowest on-time shipment rate over the most recent six months?

- **Tag:** SQL
- **Expected tools:** `query_database`
- **Scenario:** general operational analysis
- **Expected outcome:** factual result
- **Evaluation:** numeric correctness + correct supplier set + correct date filter

**Q02 — CR3 deterioration**
> How has Carrier CR3's average shipment delay changed month by month over the last 12 months?

- **Tag:** SQL
- **Expected tools:** `query_database`
- **Scenario:** RC-03
- **Expected outcome:** 🟢 Supported
- **Evaluation:** correct monthly series and trend; no unsupported causal claim

**Q03 — WH-2 stage localization**
> During the peak-demand period, did delays originate upstream in inbound shipments or downstream in deliveries from WH-2?

- **Tag:** SQL
- **Expected tools:** `query_database`
- **Scenario:** RC-04
- **Expected outcome:** 🟢 Supported
- **Evaluation:** compare inbound shipment delay against outbound delivery delay for the
  same warehouse/period; correct-stage conclusion required

**Q04 — SLA breaches**
> Which suppliers violated their contractual lead-time SLA most frequently during the last year?

- **Tag:** SQL
- **Expected tools:** `query_database`
- **Scenario:** RC-02 + background
- **Expected outcome:** factual result
- **Evaluation:** SLA computed from contract terms versus actual timing

**Q05 — S07 clean-route comparison**
> Is S07 still significantly late on routes that do not pass through PORT-GEN, compared with other suppliers using those clean routes?

- **Tag:** SQL
- **Expected tools:** `query_database`
- **Scenario:** RC-02
- **Expected outcome:** 🟢 Supported
- **Evaluation:** must show the controlled peer comparison; naming S07 alone is not sufficient

### 10.2 RAG-heavy / document-focused

**Q06 — Shipment incident report**
> What happened to shipment SH-4921, according to the incident documentation?

- **Tag:** RAG
- **Expected tools:** `search_documents`, optionally `query_database`
- **Scenario:** RC-07
- **Expected outcome:** 🟢 Supported
- **Evaluation:** incident code, date, type, and causal statement must trace to the cited report

**Q07 — Contract terms**
> What delivery lead time and penalty terms apply to supplier S07?

- **Tag:** RAG
- **Expected tools:** `search_documents`
- **Scenario:** RC-02
- **Expected outcome:** 🟢 Supported
- **Evaluation:** contract evidence must support both the lead time and penalty wording

**Q08 — Port bulletin**
> What disruption did PORT-GEN report during Q1, and which routes or dates did the bulletin identify?

- **Tag:** RAG
- **Expected tools:** `search_documents`
- **Scenario:** RC-01
- **Expected outcome:** 🟢 Supported
- **Evaluation:** retrieved bulletin(s), port code, disruption period, and affected routes

### 10.3 Multi-source investigations

**Q09 — Explain PORT-GEN delay spike**
> Why did shipments using PORT-GEN experience elevated delays during Q1?

- **Tag:** MULTI
- **Expected tools:** `query_database` + `search_documents` + `verify_evidence`
- **Scenario:** RC-01
- **Expected outcome:** 🟢 Supported
- **Evaluation:** SQL establishes the pattern; documents establish the congestion explanation;
  final claim must bind both

**Q10 — Explain CR3 deterioration**
> Why has Carrier CR3's performance deteriorated over time?

- **Tag:** MULTI
- **Expected tools:** `query_database` + `search_documents` + `verify_evidence`
- **Scenario:** RC-03
- **Expected outcome:** 🟡 Partially supported
- **Evaluation:** trend is supported; no single definitive root cause may be invented

**Q11 — Supplier-specific cause with control comparison**
> Why does S07 have persistent delivery problems, and how can you show that the problem
> is not explained only by PORT-GEN congestion?

- **Tag:** MULTI
- **Expected tools:** `query_database` + `search_documents` + `verify_evidence`
- **Scenario:** RC-02
- **Expected outcome:** 🟢 Supported
- **Evaluation:** reasoning-aware; requires clean-route comparison, peer comparison, and
  documentary/contract corroboration

### 10.4 Genuine graph investigations

**Q12 — Port disruption blast radius**
> Which customers were exposed to the Q1 PORT-GEN disruption through shipments routed through the affected port?

- **Tag:** GRAPH
- **Expected tools:** `graph_query` + optional document verification
- **Scenario:** RC-01 / RC-05
- **Expected outcome:** 🟢 Supported
- **Evaluation:** customer set must be derivable from the expected graph paths

**Q13 — Shared-route supplier network**
> Which suppliers share the disrupted RT-04 route with S07, and which customers are downstream of that shared route?

- **Tag:** GRAPH
- **Expected tools:** `graph_query`
- **Scenario:** RC-05
- **Expected outcome:** 🟢 Supported
- **Evaluation:** must return the intended four-supplier network and correct downstream
  customer relationships; supplier membership alone does not earn full credit

**Q14 — Multi-supplier customer exposure**
> Which customers are connected to more than one of the suppliers exposed to the RT-04 / PORT-GEN disruption?

- **Tag:** GRAPH
- **Expected tools:** `graph_query`
- **Scenario:** RC-05
- **Expected outcome:** 🟢 Supported
- **Evaluation:** customer must be connected through multiple valid supplier→shipment→route
  paths; this is a graph overlap question, not a supplier count

### 10.5 Refusal / insufficient evidence

**Q15 — Unexplained shipment delay**
> Shipment SH-XXXX was delayed. What caused the delay?

- **Tag:** MULTI
- **Expected tools:** `query_database` + `search_documents` + `verify_evidence`
- **Scenario:** RC-06
- **Expected outcome:** 🔴 **Insufficient evidence**
- **Evaluation:** acknowledge the observed delay, report any contextual evidence found,
  and explicitly refuse to assert a cause without direct evidence for the target shipment

`SH-XXXX` is substituted by a generated RC-06 target ID in the benchmark instance.
The corresponding target shipment and contextual documents are stored in the separate
ground-truth artifact.

### 10.6 Benchmark coverage matrix

| Question | SQL | RAG | GRAPH | MULTI | Key behavior |
|---|:---:|:---:|:---:|:---:|---|
| Q01 | ✓ |  |  |  | aggregation |
| Q02 | ✓ |  |  |  | temporal trend |
| Q03 | ✓ |  |  |  | stage localization |
| Q04 | ✓ |  |  |  | SLA reasoning |
| Q05 | ✓ |  |  |  | controlled comparison |
| Q06 |  | ✓ |  |  | precise retrieval |
| Q07 |  | ✓ |  |  | contract evidence |
| Q08 |  | ✓ |  |  | operational bulletin |
| Q09 | ✓ | ✓ |  | ✓ | structured + document fusion |
| Q10 | ✓ | ✓ |  | ✓ | partial support |
| Q11 | ✓ | ✓ |  | ✓ | reasoning + de-confounding |
| Q12 |  |  | ✓ |  | graph blast radius |
| Q13 |  |  | ✓ |  | shared-network traversal |
| Q14 |  |  | ✓ |  | graph overlap |
| Q15 | ✓ | ✓ |  | ✓ | refusal under contextual noise |

The benchmark intentionally has **5 SQL-only, 3 RAG-heavy, 3 GRAPH, and 4 MULTI** questions.
RC-02, RC-03, RC-04, RC-05, and RC-06 are not merely present in the data; they are
tested through behaviors that can fail in different ways.

## OPEN QUESTIONS TO RESOLVE BEFORE GENERATING DATA

1. **Vector store:** Qdrant (spec's choice, good keyword) vs reuse Chroma from GDPR
   (zero new infra, saves a day). Recommendation: start Chroma, swap to Qdrant at
   Layer 3/4 if time allows. Not yet decided.
2. **LLM for prose generation:** same Ollama model as the agent, or a smaller/faster
   one just for bulk document generation? (Generation is ~600–900 calls; a small model
   is fine since facts are fixed and validated.)
3. **Exact seed value + generator determinism test:** use one committed seed; add a test
   that regenerates and checks row counts, checksums, and the generated ground-truth
   artifact, so "reproducible" is proven not claimed.
4. **How much background noise vs seeded signal:** ratio of `root_cause_id IS NULL`
   incidents/documents to seeded ones. Too little noise makes retrieval trivially easy
   (the GDPR "all-easy-questions" trap); too much buries the signal. Start ~70% noise /
   30% seeded and measure the resulting retrieval difficulty.
5. **Minimum evidence floor per SUPPORTED scenario:** define the minimum number of
   independently useful corroborating documents / structured facts required for a seeded
   scenario to remain a valid evaluation case. This must be decided during generator
   design so an agent failure cannot be confused with an undertestable benchmark case.
6. **Reasoning trace contract for the agent (Section 11):** define the structured artifact
   the agent must emit so reasoning-aware evaluation is implementable. At minimum this
   should bind claims to evidence/tool results without exposing hidden ground-truth labels
   to the agent.
```