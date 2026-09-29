"""
STAGE 11b — deterministic validation gate over generated prose.

For each document: assert every required code/date/number appears; assert NO foreign
codes appear (regex for S\\d+, SH-\\d+, INC-\\d+, PO-\\d+, DL-\\d+, INV-\\d+, C\\d+ that
don't belong to this skeleton). On failure, prose.py regenerates up to
config.PROSE_MAX_RETRIES, then falls back to skeleton text. This is what lets you trust
LLM prose without trusting the LLM.
"""
from __future__ import annotations
import re
import datagen.config as config
from datagen.model import GeneratedDocument

CODE_PATTERNS = {
    "supplier": re.compile(r"\bS\d{2,}\b"),
    "shipment": re.compile(r"\bSH-\d+\b"),
    "incident": re.compile(r"\bINC-\d+\b"),
    "po": re.compile(r"\bPO-\d+\b"),
    "delivery": re.compile(r"\bDL-\d+\b"),
    "invoice": re.compile(r"\bINV-\d+\b"),
    "customer": re.compile(r"\bC\d{2,}\b"),
}


def validate(doc: GeneratedDocument) -> bool:
    """Return True iff required facts present AND no foreign codes leaked."""
    raise NotImplementedError
