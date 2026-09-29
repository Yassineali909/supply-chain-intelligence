"""
Persist the structured source of truth to PostgreSQL (stages 1-8).

Postgres is a PROJECTION of the in-memory dataset, so this writer is IDEMPOTENT: it
drops and recreates the whole schema every run and never appends to a stale one (the
direct lesson from the GDPR stale-index bug).

THE HIDDEN-LEVER STRIP — the reason this project's RC-02 is a real investigation:
the agent-visible schema OMITS reliability_tier, perf_trend, and congestion_season.
Those columns exist on the dataclasses for verification, but they are never written
here, so the agent physically cannot read the answer — it must investigate the delays.

Connection comes from config.DATABASE_URL (env-overridable; safe local default).
"""
from __future__ import annotations

import psycopg2
from psycopg2.extras import execute_values

import datagen.config as config


SCHEMA_SQL = """
DROP TABLE IF EXISTS supplier_performance CASCADE;
DROP TABLE IF EXISTS incidents CASCADE;
DROP TABLE IF EXISTS invoices CASCADE;
DROP TABLE IF EXISTS deliveries CASCADE;
DROP TABLE IF EXISTS shipments CASCADE;
DROP TABLE IF EXISTS order_items CASCADE;
DROP TABLE IF EXISTS purchase_orders CASCADE;
DROP TABLE IF EXISTS supplier_contracts CASCADE;
DROP TABLE IF EXISTS suppliers CASCADE;
DROP TABLE IF EXISTS routes CASCADE;
DROP TABLE IF EXISTS warehouses CASCADE;
DROP TABLE IF EXISTS ports CASCADE;
DROP TABLE IF EXISTS carriers CASCADE;
DROP TABLE IF EXISTS customers CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS product_categories CASCADE;

CREATE TABLE product_categories (
    category_id  INT PRIMARY KEY,
    name         TEXT NOT NULL
);
CREATE TABLE products (
    product_id   INT PRIMARY KEY,
    sku          TEXT UNIQUE NOT NULL,
    name         TEXT NOT NULL,
    category_id  INT REFERENCES product_categories(category_id),
    unit_cost    NUMERIC(10,2)
);
CREATE TABLE suppliers (
    supplier_id  INT PRIMARY KEY,
    code         TEXT UNIQUE NOT NULL,
    name         TEXT NOT NULL,
    country      TEXT,
    onboarded_on DATE
);
CREATE TABLE supplier_contracts (
    contract_id      INT PRIMARY KEY,
    supplier_id      INT REFERENCES suppliers(supplier_id),
    agreed_lead_days INT NOT NULL,
    penalty_clause   TEXT,
    valid_from       DATE,
    valid_to         DATE
);
CREATE TABLE customers (
    customer_id  INT PRIMARY KEY,
    code         TEXT UNIQUE NOT NULL,
    name         TEXT NOT NULL,
    country      TEXT,
    priority_tier TEXT
);
CREATE TABLE carriers (
    carrier_id   INT PRIMARY KEY,
    code         TEXT UNIQUE NOT NULL,
    name         TEXT NOT NULL,
    mode         TEXT
);
CREATE TABLE ports (
    port_id      INT PRIMARY KEY,
    code         TEXT UNIQUE NOT NULL,
    name         TEXT NOT NULL,
    country      TEXT
);
CREATE TABLE warehouses (
    warehouse_id INT PRIMARY KEY,
    code         TEXT UNIQUE NOT NULL,
    name         TEXT NOT NULL,
    region       TEXT,
    capacity_units INT
);
CREATE TABLE routes (
    route_id     INT PRIMARY KEY,
    code         TEXT UNIQUE NOT NULL,
    name         TEXT NOT NULL,
    origin_region TEXT,
    port_id      INT REFERENCES ports(port_id),
    warehouse_id INT REFERENCES warehouses(warehouse_id),
    planned_transit_days INT
);
CREATE TABLE purchase_orders (
    po_id        INT PRIMARY KEY,
    po_code      TEXT UNIQUE NOT NULL,
    supplier_id  INT REFERENCES suppliers(supplier_id),
    order_date   DATE,
    promised_date DATE,
    status       TEXT
);
CREATE TABLE order_items (
    item_id      INT PRIMARY KEY,
    po_id        INT REFERENCES purchase_orders(po_id),
    product_id   INT REFERENCES products(product_id),
    quantity     INT,
    line_amount  NUMERIC(12,2)
);
CREATE TABLE shipments (
    shipment_id      INT PRIMARY KEY,
    shipment_code    TEXT UNIQUE NOT NULL,
    po_id            INT REFERENCES purchase_orders(po_id),
    route_id         INT REFERENCES routes(route_id),
    carrier_id       INT REFERENCES carriers(carrier_id),
    mode             TEXT,
    planned_departure DATE,
    planned_arrival  DATE,
    actual_departure DATE,
    actual_arrival   DATE,
    delay_days       INT,
    status           TEXT
);
CREATE TABLE deliveries (
    delivery_id  INT PRIMARY KEY,
    delivery_code TEXT UNIQUE NOT NULL,
    shipment_id  INT REFERENCES shipments(shipment_id),
    customer_id  INT REFERENCES customers(customer_id),
    warehouse_id INT REFERENCES warehouses(warehouse_id),
    planned_date DATE,
    actual_date  DATE,
    delay_days   INT,
    status       TEXT
);
CREATE TABLE invoices (
    invoice_id   INT PRIMARY KEY,
    invoice_code TEXT UNIQUE NOT NULL,
    po_id        INT REFERENCES purchase_orders(po_id),
    amount       NUMERIC(12,2),
    issued_date  DATE,
    due_date     DATE,
    paid_date    DATE,
    disputed     BOOLEAN,
    status       TEXT
);
CREATE TABLE incidents (
    incident_id  INT PRIMARY KEY,
    incident_code TEXT UNIQUE NOT NULL,
    incident_type TEXT,
    severity     TEXT,
    occurred_on  DATE,
    shipment_id  INT REFERENCES shipments(shipment_id),
    supplier_id  INT REFERENCES suppliers(supplier_id),
    port_id      INT REFERENCES ports(port_id),
    warehouse_id INT REFERENCES warehouses(warehouse_id),
    carrier_id   INT REFERENCES carriers(carrier_id)
);
CREATE TABLE supplier_performance (
    supplier_id  INT REFERENCES suppliers(supplier_id),
    period_month DATE,
    orders_count INT,
    on_time_count INT,
    avg_delay_days NUMERIC(6,2),
    sla_breach_count INT,
    PRIMARY KEY (supplier_id, period_month)
);
"""

TABLE_SPECS = [
    ("product_categories", ["category_id", "name"]),
    ("products", ["product_id", "sku", "name", "category_id", "unit_cost"]),
    ("suppliers", ["supplier_id", "code", "name", "country", "onboarded_on"]),
    ("supplier_contracts", ["contract_id", "supplier_id", "agreed_lead_days",
                            "penalty_clause", "valid_from", "valid_to"]),
    ("customers", ["customer_id", "code", "name", "country", "priority_tier"]),
    ("carriers", ["carrier_id", "code", "name", "mode"]),
    ("ports", ["port_id", "code", "name", "country"]),
    ("warehouses", ["warehouse_id", "code", "name", "region", "capacity_units"]),
    ("routes", ["route_id", "code", "name", "origin_region", "port_id",
                "warehouse_id", "planned_transit_days"]),
    ("purchase_orders", ["po_id", "po_code", "supplier_id", "order_date",
                        "promised_date", "status"]),
    ("order_items", ["item_id", "po_id", "product_id", "quantity", "line_amount"]),
    ("shipments", ["shipment_id", "shipment_code", "po_id", "route_id", "carrier_id",
                "mode", "planned_departure", "planned_arrival", "actual_departure",
                "actual_arrival", "delay_days", "status"]),
    ("deliveries", ["delivery_id", "delivery_code", "shipment_id", "customer_id",
                    "warehouse_id", "planned_date", "actual_date", "delay_days", "status"]),
    ("invoices", ["invoice_id", "invoice_code", "po_id", "amount", "issued_date",
                "due_date", "paid_date", "disputed", "status"]),
    ("incidents", ["incident_id", "incident_code", "incident_type", "severity",
                "occurred_on", "shipment_id", "supplier_id", "port_id",
                "warehouse_id", "carrier_id"]),
    ("supplier_performance", ["supplier_id", "period_month", "orders_count",
                            "on_time_count", "avg_delay_days", "sla_breach_count"]),
]


def write(dataset: dict, database_url: str = None) -> None:
    """Create the agent-visible schema and bulk-insert all structured rows."""
    url = database_url or config.DATABASE_URL
    conn = psycopg2.connect(url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_SQL)
                for table, cols in TABLE_SPECS:
                    rows = dataset.get(table, [])
                    if not rows:
                        continue
                    values = [tuple(getattr(r, c) for c in cols) for r in rows]
                    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s"
                    execute_values(cur, sql, values)
        print(f"[postgres] wrote {sum(len(dataset.get(t, [])) for t, _ in TABLE_SPECS)} rows "
              f"across {len(TABLE_SPECS)} tables")
    finally:
        conn.close()
