"""
STAGE 12 — write the serialized answer key: artifacts/ground_truth/scenarios.json.

This is the "exam answer key" that must live OUTSIDE the database the agent queries.
It is produced from the SAME deterministic model as the data, so it can be regenerated
and versioned without regenerating Postgres/Neo4j/Qdrant.

THE ONE RULE THIS FILE EXISTS TO ENFORCE:
    context_for associations (which contextual-noise docs belong to which scenario)
    are written HERE and ONLY here. They must never appear in queryable document
    metadata, retrieval payloads, model-visible logs, or the benchmark prompt.
    Leaking context_for hands the agent the answer to the RC-06 refusal test.
"""
from __future__ import annotations

import datagen.config as config
from datagen.scenarios import Scenario


def write_ground_truth(scenarios: list[Scenario]) -> None:
    """
    Serialize each scenario's answer-key record to scenarios.json:
      root_cause_id, title, expected_outcome, affected_entities,
      evidence{sql_signatures, direct_causal_document_ids, context_document_ids},
      expected_paths, reasoning_requirements, direct_cause_evidence_required,
      and context_for (evaluator-only).
    """
    raise NotImplementedError


def _assert_no_context_leak(scenarios: list[Scenario], documents: list) -> None:
    """
    Safety gate: verify that every doc named in any scenario.context_for carries
    root_cause_id=None in its QUERYABLE metadata. If a context doc's metadata reveals
    its scenario, raise — the answer key would be leaking into the exam.
    """
    raise NotImplementedError
