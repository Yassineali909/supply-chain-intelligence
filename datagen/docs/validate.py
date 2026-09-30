"""
STAGE 11b — deterministic validation gate over generated text.

Passes iff every required code/date/number appears AND no foreign codes (matching a
known pattern but not in required_codes) appear — catching an invented citation.
"""
from __future__ import annotations

import re

from datagen.model import GeneratedDocument

CODE_PATTERNS = {
    "supplier": re.compile(r"\bS\d{2,}\b"),
    "shipment": re.compile(r"\bSH-\d+\b"),
    "incident": re.compile(r"\bINC-\d+\b"),
    "po": re.compile(r"\bPO-\d+\b"),
    "delivery": re.compile(r"\bDL-\d+\b"),
    "invoice": re.compile(r"\bINV-\d+\b"),
    "port": re.compile(r"\bPORT-[A-Z]+\b"),
    "warehouse": re.compile(r"\bWH-\d+\b"),
    "carrier": re.compile(r"\bCR\d+\b"),
}


def validate(doc: GeneratedDocument) -> bool:
    text = doc.text
    skel = doc.skeleton
    required = set(skel.required_codes)

    for code in skel.required_codes:
        if code not in text:
            return False
    for d in skel.required_dates:
        if d not in text:
            return False
    for n in skel.required_numbers:
        if str(n) not in text:
            return False

    found = set()
    for pat in CODE_PATTERNS.values():
        found.update(pat.findall(text))
    if found - required:
        return False

    return True


def render_and_validate(skeleton, use_llm=False):
    from datagen.docs.prose import render
    doc = render(skeleton, use_llm=use_llm)
    doc.validation_passed = validate(doc)
    return doc
