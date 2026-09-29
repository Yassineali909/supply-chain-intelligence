"""
The seven seeded root-cause scenarios, as DATA.

This file is the single source for what SHOULD be true in the dataset. It drives two
things that must never drift apart:
  1. SEEDING — stage 4/5/7 read these records to place the intended signal.
  2. ANSWER KEY — writers/ground_truth.py serializes these into scenarios.json.

Because both come from here, the exam and the answer key cannot disagree. Section 9 of
PROJECT_KNOWLEDGE.md is the prose version of this file; this is the machine-readable one.

Field notes:
  - reasoning_requirements: for scenarios (esp. RC-02) where naming the right entity is
    NOT enough — the evaluator must see the required comparison in the evidence trace.
  - context_for: EVALUATOR-ONLY associations for contextual-noise docs (RC-06). These
    NEVER enter queryable document metadata; they live only in the answer key.
  - evidence_floor: the per-scenario minimum that checks/evidence_floor.py enforces at
    generation time. An unmet floor fails the build.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import datagen.config as config


@dataclass
class Scenario:
    root_cause_id: str
    title: str
    lever: Optional[str]                     # which hidden mechanism drives it (None for RC-06)
    affected_entities: dict                  # {'suppliers': [...], 'routes_clean_for_control': [...], ...}
    time_window: Optional[str]
    needs_graph: bool
    expected_outcome: str                    # 'SUPPORTED'|'PARTIAL'|'INSUFFICIENT'
    reasoning_requirements: list = field(default_factory=list)
    direct_cause_evidence_required: bool = True
    # Populated DURING generation (not hand-written), then serialized to the answer key:
    evidence: dict = field(default_factory=dict)      # sql_signatures, direct_causal_document_ids, context_document_ids
    context_for: dict = field(default_factory=dict)   # {doc_id: root_cause_id} — evaluator only
    expected_paths: list = field(default_factory=list)  # graph path signatures (RC-05)


def all_scenarios() -> list[Scenario]:
    """
    Return the seven scenario definitions. Structure only — the evidence/context_for/
    expected_paths fields are filled in by the generator as it places and observes the
    signal, then written to scenarios.json.
    """
    raise NotImplementedError


def scenario_floor(root_cause_id: str) -> dict:
    """Return the evidence floor for a scenario (from config.EVIDENCE_FLOORS)."""
    raise NotImplementedError
