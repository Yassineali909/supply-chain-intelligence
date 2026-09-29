"""
STAGE 1 — reference/master data + HIDDEN LEVER INJECTION.

Scenario-critical entities are HAND-PINNED (ANCHORS below); everything else is filled
with seeded randomness. Hidden levers assigned here:
  S07  -> reliability_tier 'problematic'   (RC-02)
  PORT-GEN -> congestion_season 'Q1'        (RC-01)
  CR3  -> perf_trend 'degrading'            (RC-03)
  WH-2 -> tight capacity_units              (RC-04)
  RT-04 -> East-Asia -> PORT-GEN -> WH-2, shared by S07/S11/S19/S23 (RC-05)

The hidden lever columns are stored for verification but MUST be stripped from the
agent-visible schema by postgres_writer.
"""
from __future__ import annotations

from datetime import date

import datagen.config as config
from datagen.seed import child_stream
from datagen.model import (
    ProductCategory, Product, Supplier, SupplierContract, Customer,
    Carrier, Port, Warehouse, Route,
)

PORT_ANCHORS = [
    {"code": "PORT-GEN", "name": "Genoa",     "country": "Italy",       "congestion_season": config.CONGESTION_SEASON},
    {"code": "PORT-ADR", "name": "Rotterdam", "country": "Netherlands", "congestion_season": None},
    {"code": "PORT-MED", "name": "Valencia",  "country": "Spain",       "congestion_season": None},
    {"code": "PORT-ATL", "name": "Hamburg",   "country": "Germany",     "congestion_season": None},
    {"code": "PORT-BLK", "name": "Piraeus",   "country": "Greece",      "congestion_season": None},
]

WH_ANCHORS = [
    {"code": "WH-1", "name": "Lyon DC",   "region": "West",    "capacity_units": 1200},
    {"code": "WH-2", "name": "Milan DC",  "region": "South",   "capacity_units": 450},
    {"code": "WH-3", "name": "Munich DC", "region": "Central", "capacity_units": 1100},
    {"code": "WH-4", "name": "Warsaw DC", "region": "East",    "capacity_units": 1000},
]

CARRIER_ANCHORS = [
    {"code": "CR1", "name": "BlueWave Sea", "mode": "sea",  "perf_trend": "stable"},
    {"code": "CR2", "name": "IberRoad",     "mode": "road", "perf_trend": "stable"},
    {"code": "CR3", "name": "TransOcean",   "mode": "sea",  "perf_trend": "degrading"},
    {"code": "CR4", "name": "AlpineHaul",   "mode": "road", "perf_trend": "stable"},
    {"code": "CR5", "name": "MareNostrum",  "mode": "sea",  "perf_trend": "stable"},
    {"code": "CR6", "name": "EuroFreight",  "mode": "road", "perf_trend": "stable"},
]

ROUTE_ANCHORS = [
    {"code": "RT-01", "origin_region": "West-Europe",  "port": "PORT-ATL", "warehouse": "WH-1", "planned_transit_days": 6},
    {"code": "RT-02", "origin_region": "Iberia",       "port": "PORT-MED", "warehouse": "WH-1", "planned_transit_days": 5},
    {"code": "RT-03", "origin_region": "East-Asia",    "port": "PORT-GEN", "warehouse": "WH-3", "planned_transit_days": 28},
    {"code": "RT-04", "origin_region": "East-Asia",    "port": "PORT-GEN", "warehouse": "WH-2", "planned_transit_days": 30},
    {"code": "RT-05", "origin_region": "Levant",       "port": "PORT-BLK", "warehouse": "WH-4", "planned_transit_days": 12},
    {"code": "RT-06", "origin_region": "North-Africa", "port": "PORT-MED", "warehouse": "WH-2", "planned_transit_days": 8},
    {"code": "RT-07", "origin_region": "Baltic",       "port": "PORT-ATL", "warehouse": "WH-4", "planned_transit_days": 7},
    {"code": "RT-08", "origin_region": "Adriatic",     "port": "PORT-ADR", "warehouse": "WH-1", "planned_transit_days": 9},
    {"code": "RT-09", "origin_region": "East-Asia",    "port": "PORT-GEN", "warehouse": "WH-1", "planned_transit_days": 29},
    {"code": "RT-10", "origin_region": "Iberia",       "port": "PORT-MED", "warehouse": "WH-3", "planned_transit_days": 6},
    {"code": "RT-11", "origin_region": "Levant",       "port": "PORT-BLK", "warehouse": "WH-2", "planned_transit_days": 13},
    {"code": "RT-12", "origin_region": "West-Europe",  "port": "PORT-ADR", "warehouse": "WH-3", "planned_transit_days": 7},
]

CATEGORY_NAMES = ["Electronics", "Industrial Parts", "Consumables", "Textiles",
                  "Chemicals", "Automotive", "Packaging", "Machinery"]

COUNTRIES = ["Germany", "France", "Italy", "Spain", "Poland", "Netherlands",
             "China", "Japan", "Turkey", "Tunisia", "Morocco", "Greece"]


def _mk_date(y, m, d):
    return date(y, m, d)


def build_reference(root) -> dict:
    """Build all master data. Returns table_name -> list[dataclass]. Anchors pinned; rest seeded-random."""
    rng_ref = child_stream(root, "reference")

    categories = [ProductCategory(category_id=i + 1, name=n)
                  for i, n in enumerate(CATEGORY_NAMES)]

    products = []
    for i in range(config.N_PRODUCTS):
        cat = int(rng_ref.integers(1, config.N_CATEGORIES + 1))
        products.append(Product(
            product_id=i + 1, sku=f"PRD-{i + 1:04d}", name=f"Product {i + 1}",
            category_id=cat, unit_cost=round(float(rng_ref.uniform(5, 500)), 2),
        ))

    suppliers = []
    for i in range(config.N_SUPPLIERS):
        code = f"S{i + 1:02d}"
        if code in config.PROBLEMATIC_SUPPLIERS:
            tier = "problematic"
        else:
            tier = "average" if rng_ref.random() < 0.20 else "reliable"
        suppliers.append(Supplier(
            supplier_id=i + 1, code=code, name=f"Supplier {code}",
            country=str(rng_ref.choice(COUNTRIES)), onboarded_on=_mk_date(2023, 1, 1),
            reliability_tier=tier,
        ))

    contracts = []
    for s in suppliers:
        lead = int(rng_ref.integers(10, 45))
        contracts.append(SupplierContract(
            contract_id=s.supplier_id, supplier_id=s.supplier_id,
            agreed_lead_days=lead,
            penalty_clause=f"Penalty of 1.5% of order value per week of delay beyond {lead} days.",
            valid_from=_mk_date(2023, 1, 1), valid_to=_mk_date(2027, 1, 1),
        ))

    customers = []
    for i in range(config.N_CUSTOMERS):
        r = rng_ref.random()
        tier = "strategic" if r < 0.15 else "priority" if r < 0.45 else "standard"
        customers.append(Customer(
            customer_id=i + 1, code=f"C{i + 1:03d}", name=f"Customer {i + 1:03d}",
            country=str(rng_ref.choice(COUNTRIES)), priority_tier=tier,
        ))

    ports = [Port(port_id=i + 1, code=a["code"], name=a["name"],
                  country=a["country"], congestion_season=a["congestion_season"])
             for i, a in enumerate(PORT_ANCHORS)]
    port_by_code = {p.code: p for p in ports}

    warehouses = [Warehouse(warehouse_id=i + 1, code=a["code"], name=a["name"],
                            region=a["region"], capacity_units=a["capacity_units"])
                  for i, a in enumerate(WH_ANCHORS)]
    wh_by_code = {w.code: w for w in warehouses}

    carriers = [Carrier(carrier_id=i + 1, code=a["code"], name=a["name"],
                        mode=a["mode"], perf_trend=a["perf_trend"])
                for i, a in enumerate(CARRIER_ANCHORS)]

    routes = []
    for i, a in enumerate(ROUTE_ANCHORS):
        routes.append(Route(
            route_id=i + 1, code=a["code"],
            name=f"{a['origin_region']} -> {a['port']} -> {a['warehouse']}",
            origin_region=a["origin_region"],
            port_id=port_by_code[a["port"]].port_id,
            warehouse_id=wh_by_code[a["warehouse"]].warehouse_id,
            planned_transit_days=a["planned_transit_days"],
        ))

    return {
        "product_categories": categories, "products": products,
        "suppliers": suppliers, "supplier_contracts": contracts,
        "customers": customers, "ports": ports, "warehouses": warehouses,
        "carriers": carriers, "routes": routes,
    }
