"""
ALL causal-lever logic, in one auditable file.

A lever is a deterministic bias on an event's outcome, driven by a HIDDEN column
decided in stage 1. Levers are ADDITIVE and INDEPENDENT so their effects can be
disentangled by the evaluator — this is what makes RC-02's de-confounding real.

    delay_days(shipment) =
          base_noise(rng)                    # always present, symmetric
        + supplier_lever(supplier)           # RC-02
        + port_congestion_lever(route,port,date)  # RC-01
        + carrier_lever(carrier, date)       # RC-03
    # warehouse_lever applies to DELIVERY (stage 5), NOT shipment — that IS RC-04.

Each shipment function returns extra delay-days; total_shipment_delay sums them and
returns a per-lever attribution dict for the evidence floor to read.
"""
from __future__ import annotations

from datetime import date

import datagen.config as config


def _quarter(d: date) -> str:
    return f"Q{(d.month - 1) // 3 + 1}"


def base_noise(rng) -> float:
    """Small symmetric per-event noise. Always applied. Can be slightly negative
    (early arrival), but total delay is clamped at >= 0 by the caller."""
    return float(rng.normal(0.0, config.BASE_NOISE_SD))


def supplier_lever(supplier) -> float:
    """
    RC-02. Positive mean delay for 'problematic' suppliers, 0 otherwise. Route-
    INDEPENDENT: a problematic supplier is late even on clean routes — the residual
    signal the agent must isolate.
    """
    if supplier.reliability_tier == "problematic":
        return config.SUPPLIER_PROBLEMATIC_DELAY
    if supplier.reliability_tier == "average":
        return config.SUPPLIER_PROBLEMATIC_DELAY * 0.25
    return 0.0


def port_congestion_lever(route, port, when: date) -> float:
    """
    RC-01. Extra delay only when the route's port has a congestion season AND the date
    falls in it. 0 on clean routes/ports — so it never contaminates RC-02's clean-route
    comparison.
    """
    if port.congestion_season and _quarter(when) == port.congestion_season:
        return config.PORT_CONGESTION_DELAY
    return 0.0


def carrier_lever(carrier, when: date, window_start: date, window_days: int) -> float:
    """
    RC-03. Extra delay that SCALES with time elapsed for a 'degrading' carrier (0 early,
    up to CARRIER_DEGRADE_MAX_DELAY at the end of the window); 0 for stable carriers.
    """
    if carrier.perf_trend != "degrading":
        return 0.0
    elapsed = (when - window_start).days
    frac = max(0.0, min(1.0, elapsed / window_days))
    return config.CARRIER_DEGRADE_MAX_DELAY * frac


def warehouse_lever(warehouse, when: date, is_peak: bool) -> float:
    """
    RC-04. Applied to DELIVERIES (stage 5), not shipments. Extra OUTBOUND delay when a
    capacity-limited warehouse is hit during a demand peak; 0 otherwise. Threshold on
    capacity_units keeps it specific to the tight warehouse (WH-2).
    """
    if is_peak and warehouse.capacity_units <= config.WAREHOUSE_CAPACITY_TIGHT_THRESHOLD:
        return config.WAREHOUSE_SLIP_DELAY
    return 0.0


def total_shipment_delay(rng, supplier, route, port, carrier, when,
                         window_start, window_days) -> tuple:
    """
    Sum the shipment-stage levers. Returns (delay_days:int, attribution:dict).
    Generator-internal provenance; never written to the agent DB.
    """
    base = base_noise(rng)
    sup = supplier_lever(supplier)
    prt = port_congestion_lever(route, port, when)
    car = carrier_lever(carrier, when, window_start, window_days)

    raw = base + sup + prt + car
    delay = max(0, round(raw))

    attribution = {
        "base": round(base, 2),
        "supplier": round(sup, 2),
        "port": round(prt, 2),
        "carrier": round(car, 2),
    }
    return delay, attribution
