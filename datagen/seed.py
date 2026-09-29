"""
Deterministic randomness for the generator.

One ROOT seed spawns NAMED CHILD STREAMS, one per stage. Because each child is
derived from the stage's name (not draw order), adding or changing one stage leaves
the others' streams untouched — regeneration stays stable, diffs stay small.

Same SEED -> byte-identical structured output and byte-identical factual skeletons.
(LLM prose is the only non-deterministic projection; it is validated + regenerable.)
"""
from __future__ import annotations

import hashlib
import json

import numpy as np

import datagen.config as config


def seed_everything(seed: int = config.SEED) -> np.random.SeedSequence:
    """Establish the single root of all randomness. Returns the root SeedSequence."""
    return np.random.SeedSequence(seed)


def child_stream(root: np.random.SeedSequence, name: str) -> np.random.Generator:
    """
    Derive an independent, reproducible RNG for a named stage (e.g. "shipments").

    The stage name is hashed to a stable integer (NOT Python's hash(), which is
    salted per process) and mixed with the root entropy. The same (root, name) pair
    always yields the same stream, regardless of the order stages are requested in.
    """
    name_int = int(hashlib.sha256(name.encode()).hexdigest(), 16) % (2**32)
    child = np.random.SeedSequence(entropy=[root.entropy, name_int])
    return np.random.default_rng(child)


def checksum_structured(tables: dict) -> str:
    """
    Stable checksum over the structured tables (excluding LLM prose), for the
    determinism test: regenerate twice, assert identical checksum.

    `tables` maps table_name -> list of dataclass instances (or dicts).
    """
    from dataclasses import asdict, is_dataclass

    def normalize(rows):
        out = []
        for r in rows:
            d = asdict(r) if is_dataclass(r) else dict(r)
            d = {k: v for k, v in d.items() if not k.startswith("_")}
            out.append(d)
        return out

    payload = {name: normalize(rows) for name, rows in sorted(tables.items())}
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()
