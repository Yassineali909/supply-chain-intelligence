"""
Typed records for every entity and document the generator produces.

These dataclasses ARE the schema contract between stages. A later stage may only
read fields that an earlier stage populated (see the generation order in
GENERATOR_DESIGN.md §1). Keeping them typed makes the topological dependency between
stages explicit and catches "document references a code that doesn't exist yet" bugs
at construction time rather than at eval time.

Hidden ground-truth levers (reliability_tier, perf_trend, congestion_season) live on
the entity records so the generator and YOU can verify the data — but they are
stripped from the schema the agent's text-to-SQL layer sees. Do not leak them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


# ─────────────────────────── Reference / master data ───────────────────────────

@dataclass
class ProductCategory:
    category_id: int
    name: str


@dataclass
class Product:
    product_id: int
    sku: str
    name: str
    category_id: int
    unit_cost: float


@dataclass
class Supplier:
    supplier_id: int
    code: str                       # 'S07' — appears in documents & citations
    name: str
    country: str
    onboarded_on: date
    reliability_tier: str           # HIDDEN LEVER: 'reliable'|'average'|'problematic'


@dataclass
class SupplierContract:
    contract_id: int
    supplier_id: int
    agreed_lead_days: int           # the SLA breaches are measured against
    penalty_clause: str             # also appears verbatim-ish in the contract document
    valid_from: date
    valid_to: date


@dataclass
class Customer:
    customer_id: int
    code: str                       # 'C031'
    name: str
    country: str
    priority_tier: str              # 'standard'|'priority'|'strategic'


@dataclass
class Carrier:
    carrier_id: int
    code: str                       # 'CR3'
    name: str
    mode: str                       # 'sea'|'road'
    perf_trend: str                 # HIDDEN LEVER: 'stable'|'degrading'


@dataclass
class Port:
    port_id: int
    code: str                       # 'PORT-GEN'
    name: str
    country: str
    congestion_season: Optional[str]  # HIDDEN LEVER: e.g. 'Q1' or None


@dataclass
class Warehouse:
    warehouse_id: int
    code: str                       # 'WH-2'
    name: str
    region: str
    capacity_units: int             # ceiling that interacts with the demand peak (RC-04)


@dataclass
class Route:
    route_id: int
    code: str                       # 'RT-04'
    name: str                       # 'East-Asia -> PORT-GEN -> WH-2'
    origin_region: str
    port_id: int
    warehouse_id: int
    planned_transit_days: int


# ─────────────────────────── Transactional / event data ────────────────────────

@dataclass
class PurchaseOrder:
    po_id: int
    po_code: str                    # 'PO-10432'
    supplier_id: int
    order_date: date
    promised_date: date             # order_date + contract agreed_lead_days
    status: str                     # 'open'|'fulfilled'|'cancelled'


@dataclass
class OrderItem:
    item_id: int
    po_id: int
    product_id: int
    quantity: int
    line_amount: float


@dataclass
class Shipment:
    shipment_id: int
    shipment_code: str              # 'SH-4921' — heavily referenced in documents
    po_id: int
    route_id: int
    carrier_id: int
    mode: str
    planned_departure: date
    planned_arrival: date
    actual_departure: date
    actual_arrival: Optional[date]  # None if in transit
    delay_days: int                 # actual_arrival - planned_arrival (materialized)
    status: str
    # Generator-internal provenance (NOT written to the agent-visible DB):
    _delay_attribution: dict = field(default_factory=dict)  # {lever_name: days} for evidence floor


@dataclass
class Delivery:
    delivery_id: int
    delivery_code: str              # 'DL-8830'
    shipment_id: int
    customer_id: int
    warehouse_id: int
    planned_date: date
    actual_date: Optional[date]
    delay_days: int
    status: str
    _delay_attribution: dict = field(default_factory=dict)  # warehouse lever recorded here (RC-04)


@dataclass
class Invoice:
    invoice_id: int
    invoice_code: str               # 'INV-22014'
    po_id: int
    amount: float
    issued_date: date
    due_date: date
    paid_date: Optional[date]
    disputed: bool
    status: str


@dataclass
class Incident:
    incident_id: int
    incident_code: str              # 'INC-042' — referenced in reports & citations
    incident_type: str              # 'delay'|'customs_hold'|'port_congestion'|...
    severity: str
    occurred_on: date
    shipment_id: Optional[int] = None
    supplier_id: Optional[int] = None
    port_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    carrier_id: Optional[int] = None
    root_cause_id: Optional[str] = None  # 'RC-01'... for seeded; None for background


# ─────────────────────────── Documents (unstructured projection) ────────────────

@dataclass
class DocumentSkeleton:
    """
    STAGE 10 output: the LOCKED FACTS a document must contain, pulled from structured
    rows. Deterministic. Prose is generated FROM this; validation checks AGAINST it.
    """
    doc_id: str                     # 'DOC-000317'
    doc_type: str                   # 'incident_report'|'supplier_email'|...
    required_codes: list            # codes that MUST appear (e.g. ['S07','SH-4921','INC-042'])
    required_dates: list            # dates that MUST appear
    required_numbers: list          # numbers that MUST appear (e.g. delay_days)
    cause_hint: Optional[str]       # e.g. 'port congestion' — guides prose, not a new fact
    # Queryable metadata (goes to the vector store). NOTE: root_cause_id here is set
    # ONLY for direct-evidence docs. Context-noise docs carry root_cause_id=None; their
    # association is recorded ONLY in the answer key via context_for.
    metadata: dict = field(default_factory=dict)


@dataclass
class GeneratedDocument:
    """STAGE 11 output: skeleton + final prose (LLM or --no-llm passthrough)."""
    skeleton: DocumentSkeleton
    text: str
    llm_generated: bool             # False if produced by the --no-llm fallback
    validation_passed: bool
