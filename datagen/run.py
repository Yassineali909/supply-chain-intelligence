"""
Generator orchestrator — runs the 12 stages in dependency order.

    python -m datagen.run                 # full run (LLM prose via Ollama)
    python -m datagen.run --no-llm        # skeleton-text docs, no Ollama needed (CI)
    python -m datagen.run --seed 123      # override the seed

The order below is not cosmetic — it is the topological sort that creates the
correlations (see GENERATOR_DESIGN.md §1). A later stage may only read stages above
it. Reordering breaks the data.

The run FAILS NON-ZERO if any evidence floor is unmet: a weak dataset never ships, so
a later eval failure is never ambiguous between "agent bug" and "data bug".
"""
from __future__ import annotations

import argparse

import datagen.config as config
from datagen.seed import seed_everything


def run(seed: int = config.SEED, use_llm: bool = True) -> None:
    """
    Execute stages 0–12. Each stage writes into an in-memory dataset dict, then the
    writers persist to PostgreSQL, the document store, and the artifacts.
    """
    root = seed_everything(seed)

    # STAGE 1  reference/master data (+ hidden levers)         stage1_reference.py
    # STAGE 2  demand curve                                    stage2_demand.py
    # STAGE 3  purchase orders + items                         stage3_orders.py
    # STAGE 4  shipments (APPLY LEVERS — causal heart)         stage4_shipments.py
    # STAGE 5  deliveries (warehouse slip — RC-04)             stage5_deliveries.py
    # STAGE 6  invoices                                        stage6_invoices.py
    # STAGE 7  incidents (seeded vs background)                stage7_incidents.py
    # STAGE 8  supplier_performance rollup                     stage8_performance.py
    # --- persist source of truth before projections ---
    #          postgres_writer.write(dataset)
    # STAGE 9  graph projection (from Postgres only)           graph_projection.py
    # STAGE 10 document skeletons                              docs/skeletons.py
    # STAGE 11 document prose + validation                     docs/prose.py, docs/validate.py
    #          document_writer.write(documents)                # plain records, NOT embedded
    # STAGE 12 manifest + ground truth + EVIDENCE FLOOR CHECK  writers/*, checks/evidence_floor.py
    raise NotImplementedError


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Supply-chain synthetic data generator")
    parser.add_argument("--seed", type=int, default=config.SEED)
    parser.add_argument("--no-llm", action="store_true",
                        help="skip LLM prose; emit skeleton text (CI / offline)")
    args = parser.parse_args()
    run(seed=args.seed, use_llm=not args.no_llm)


if __name__ == "__main__":
    _cli()
