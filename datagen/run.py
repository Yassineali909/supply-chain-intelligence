"""
Generator orchestrator — runs the structured stages in dependency order.

    python -m datagen.run                 # full run (LLM prose via Ollama) [docs: later]
    python -m datagen.run --no-llm        # skeleton-text docs, no Ollama needed [later]
    python -m datagen.run --seed 123      # override the seed

The order below is the topological sort that creates the correlations (see
GENERATOR_DESIGN.md §1). A later stage may only read stages above it.

CURRENT SCOPE: stages 1-8 (the structured source of truth) + summary. The persistence
writers (Postgres), the graph projection, and the document pipeline are wired in as
those pieces are built. Each is marked TODO below in its correct position.
"""
from __future__ import annotations

import argparse
from collections import Counter

import datagen.config as config
from datagen.seed import seed_everything
from datagen.stage1_reference import build_reference
from datagen.stage3_orders import build_orders
from datagen.stage4_shipments import build_shipments
from datagen.stage5_deliveries import build_deliveries
from datagen.stage6_invoices import build_invoices
from datagen.stage7_incidents import build_incidents
from datagen.stage8_performance import build_performance


def generate(seed: int = config.SEED, use_llm: bool = True) -> dict:
    """
    Execute the structured stages and return the full in-memory dataset dict.
    (Persistence + projections are layered on separately.)
    """
    root = seed_everything(seed)

    reference = build_reference(root)
    orders = build_orders(root, reference)
    shipments = build_shipments(root, reference, orders)
    deliveries = build_deliveries(root, reference, orders, shipments)
    invoices = build_invoices(root, reference, orders)
    incidents = build_incidents(root, reference, orders, shipments, deliveries)
    performance = build_performance(reference, orders, shipments)

    dataset = {
        **reference,
        **orders,
        **shipments,
        **deliveries,
        **invoices,
        **incidents,
        **performance,
    }

    # --- persist source of truth (TODO: writers/postgres_writer.py) ---
    # STAGE 9  — graph projection      (TODO: graph_projection.py)
    # STAGE 10 — document skeletons    (TODO: docs/skeletons.py)
    # STAGE 11 — document prose+validate (TODO: docs/prose.py, docs/validate.py)
    # STAGE 12 — manifest + ground truth + evidence floor (TODO: writers/*, checks/*)

    return dataset


def _summary(dataset: dict) -> None:
    """Print a compact, legible summary of what was generated."""
    def n(key):
        return len(dataset.get(key, []))

    print("=" * 60)
    print("GENERATION SUMMARY")
    print("=" * 60)
    for key in ["suppliers", "customers", "products", "warehouses", "ports",
                "carriers", "routes", "supplier_contracts", "purchase_orders",
                "order_items", "shipments", "deliveries", "invoices",
                "incidents", "supplier_performance"]:
        print(f"  {key:22s} {n(key):>6d}")

    incs = dataset.get("incidents", [])
    by_rc = Counter(i.root_cause_id or "BACKGROUND" for i in incs)
    seeded = sum(1 for i in incs if i.root_cause_id)
    print("-" * 60)
    print("  incidents by root cause:")
    for k in ["RC-01", "RC-02", "RC-03", "RC-04", "RC-07", "BACKGROUND"]:
        print(f"    {k:12s} {by_rc[k]:>5d}")
    if incs:
        print(f"  seeded fraction: {seeded/len(incs):.2f} (target {config.SEEDED_FRACTION})")

    ships = dataset.get("shipments", [])
    rc06_ids = {s.shipment_id for s in ships if getattr(s, "_rc06_target", False)}
    leaked = [i for i in incs if i.shipment_id in rc06_ids]
    print(f"  RC-06 targets: {len(rc06_ids)} | incidents referencing them: {len(leaked)} "
          f"({'CLEAN' if not leaked else 'LEAK!'})")
    print("=" * 60)


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Supply-chain synthetic data generator")
    parser.add_argument("--seed", type=int, default=config.SEED)
    parser.add_argument("--no-llm", action="store_true",
                        help="skip LLM prose; emit skeleton text (docs stage, later)")
    args = parser.parse_args()

    dataset = generate(seed=args.seed, use_llm=not args.no_llm)
    _summary(dataset)


if __name__ == "__main__":
    _cli()
