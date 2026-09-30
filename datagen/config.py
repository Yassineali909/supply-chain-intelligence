"""
Central configuration for the deterministic supply-chain data generator.

Every tunable knob lives here so the whole dataset can be reasoned about and
regenerated from one place — the same discipline as the GDPR project's config.py.
Nothing in the generator should hardcode a count, a probability, or a lever
strength; it should read it from here.
"""
from pathlib import Path

# --- Paths ---
ROOT = Path(__file__).parent.parent
ARTIFACTS_DIR = ROOT / "artifacts"
GROUND_TRUTH_DIR = ARTIFACTS_DIR / "ground_truth"
DOCS_OUT_DIR = ARTIFACTS_DIR / "documents"          # plain doc records (NOT embedded)
MANIFEST_PATH = ARTIFACTS_DIR / "generation_manifest.json"
SCENARIOS_PATH = GROUND_TRUTH_DIR / "scenarios.json"

# --- Determinism ---
SEED = 20260929                                      # one root seed drives everything
GENERATOR_VERSION = "0.1.0"

# --- Scale (medium, per PROJECT_KNOWLEDGE.md settled decisions) ---
N_SUPPLIERS = 30
N_PRODUCTS = 120
N_CATEGORIES = 8
N_CUSTOMERS = 60
N_WAREHOUSES = 4
N_PORTS = 5
N_CARRIERS = 6
N_ROUTES = 12
N_PURCHASE_ORDERS = 3000
MONTHS = 24                                          # operating window

# --- Time ---
# The 24-month window ends "recently" so "this month vs last" is meaningful.
END_DATE = "2026-08-31"                              # inclusive end of the window

# --- Seasonality ---
DEMAND_PEAK_MONTHS = ("2026-06", "2026-07")          # interacts with WH-2 capacity (RC-04)

# --- Causal lever strengths (mean extra delay-days; see levers.py) ---
# These are the dials that make RC-01..RC-04 real. Kept explicit and auditable.
BASE_NOISE_SD = 1.5                                  # symmetric per-shipment noise
SUPPLIER_PROBLEMATIC_DELAY = 5.0                     # RC-02: mean extra days for problematic
PORT_CONGESTION_DELAY = 4.0                          # RC-01: mean extra days in congestion season
CARRIER_DEGRADE_MAX_DELAY = 4.0                      # RC-03: max extra days at end of window
WAREHOUSE_SLIP_DELAY = 3.5                           # RC-04: mean extra delivery days at peak

# --- Hidden ground-truth levers (assigned to specific entities) ---
# These codes are decided here so scenarios.py and levers.py agree.
PROBLEMATIC_SUPPLIERS = ("S07",)                     # RC-02
CONGESTED_PORT = "PORT-GEN"                          # RC-01
CONGESTION_SEASON = "Q1"                             # RC-01
DEGRADING_CARRIER = "CR3"                            # RC-03
CAPACITY_LIMITED_WAREHOUSE = "WH-2"                  # RC-04
RC05_SUPPLIERS = ("S07", "S11", "S19", "S23")        # RC-05 shared-route network
RC05_SHARED_ROUTE = "RT-04"                          # RC-05 / RC-01 (through PORT-GEN)

# --- RC-02 de-confounding control ---
# S07 must have enough shipments on CLEAN (non-PORT-GEN) routes for a peer comparison,
# else the supplier signal can't be separated from the port signal. Enforced by the
# evidence floor — build fails if unmet.
RC02_MIN_CLEAN_ROUTE_SHIPMENTS = 25

# --- Noise/signal ratio (KB open question #4; start here, then MEASURE) ---
SEEDED_FRACTION = 0.30                                # ~30% scenario-associated, ~70% background

# --- Document counts (approximate targets; generator computes actuals) ---
N_DOCUMENTS_TARGET = 750

# --- Evidence floors (answers forward-pointer #1; checks/evidence_floor.py enforces) ---
# Per-scenario minimums. If any is unmet, generation EXITS NON-ZERO — a weak dataset
# never ships, so an eval failure is never ambiguous between "agent bug" and "data bug".
EVIDENCE_FLOORS = {
    "RC-01": {"min_docs": 6, "min_affected_shipments": 20},
    "RC-02": {"min_clean_route_shipments": RC02_MIN_CLEAN_ROUTE_SHIPMENTS,
              "min_docs": 8, "contract_doc_required": True},
    "RC-03": {"min_docs": 6, "min_months_trend": 6},
    "RC-04": {"min_docs": 4, "inbound_normal_outbound_late": True},
    "RC-05": {"n_suppliers": 4, "min_customer_overlap": 2, "max_customer_overlap": 8},
    "RC-06": {"min_context_docs": 2, "exact_direct_docs": 0, "exact_seeded_incidents": 0},
    "RC-07": {"exact_incidents": 1, "exact_docs": 1},
}

# --- LLM prose (STAGE 11) ---
LLM_MODEL = "mistral"                                 # same Ollama stack as GDPR
PROSE_MAX_RETRIES = 3                                 # regenerate on validation failure, then fallback

# Warehouse capacity threshold: warehouses at/below this are "tight" (RC-04 fires here)
WAREHOUSE_CAPACITY_TIGHT_THRESHOLD = 500

# --- Postgres (source-of-truth persistence) ---
import os
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://meridian_user:CHANGE_ME@localhost:5432/meridian"
)
