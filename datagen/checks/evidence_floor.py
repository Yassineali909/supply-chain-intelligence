"""
STAGE 12 build gate — enforce the evidence floor for every SUPPORTED scenario.

This is the concrete answer to forward-pointer #1 in the knowledge base. Without it,
"did enough evidence get generated?" is a question you only discover at eval time,
when a scenario fails and you can't tell whether the AGENT is wrong or the DATA is
too thin to test. This check moves that discovery to generation time and makes a weak
dataset FAIL THE BUILD.

Each scenario declares a floor in config.EVIDENCE_FLOORS. The check reads the actual
generated dataset + the per-scenario counts and asserts each floor is met. On any
failure it raises EvidenceFloorError, which run.py lets propagate as a non-zero exit.
"""
from __future__ import annotations

import datagen.config as config


class EvidenceFloorError(AssertionError):
    """Raised when a scenario's generated evidence is below its declared floor."""


def check_all(dataset: dict, documents: list, manifest_counts: dict) -> None:
    """
    Run every per-scenario floor check. Raise EvidenceFloorError listing ALL failures
    (not just the first) so a single run tells you everything that's thin.
    """
    raise NotImplementedError


def _check_rc01(dataset, documents) -> list:
    """>= min_docs corroborating docs AND >= min_affected_shipments on PORT-GEN in Q1."""
    raise NotImplementedError


def _check_rc02(dataset, documents) -> list:
    """
    THE important one. Assert:
      - S07 has >= RC02_MIN_CLEAN_ROUTE_SHIPMENTS shipments on NON-PORT-GEN routes,
      - those clean-route shipments still show elevated delay (supplier lever landed),
      - >= min_docs S07 docs exist AND the contract doc is present.
    If the clean-route count is unmet, RC-02 de-confounding is untestable → fail.
    """
    raise NotImplementedError


def _check_rc03(dataset, documents) -> list:
    """CR3 delay trends upward across >= min_months_trend months; >= min_docs late-dated docs."""
    raise NotImplementedError


def _check_rc04(dataset, documents) -> list:
    """
    Assert the stage-localization invariant holds: for WH-2 in the peak window,
    INBOUND shipment delay is ~normal while OUTBOUND delivery delay is elevated.
    If inbound is also elevated, the trap is broken (agent could blame the supplier
    and be 'right') → fail.
    """
    raise NotImplementedError


def _check_rc05(dataset, documents) -> list:
    """4 suppliers on RT-04; downstream customer overlap within [min,max] range."""
    raise NotImplementedError


def _check_rc06(dataset, documents) -> list:
    """
    Assert the negative is clean: the target shipment(s) have EXACTLY 0 direct-causal
    docs and 0 seeded incidents, but >= min_context_docs contextual docs exist. Also
    assert those context docs carry root_cause_id=None in queryable metadata (the
    association lives only in context_for). If a direct doc leaked in, the refusal
    test is invalid → fail.
    """
    raise NotImplementedError


def _check_rc07(dataset, documents) -> list:
    """Exactly 1 explanatory incident and exactly 1 doc for the isolated customs hold."""
    raise NotImplementedError
