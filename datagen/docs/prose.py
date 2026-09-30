"""
STAGE 11a — turn a skeleton into document text.

--no-llm (default for now): deterministic template text from the skeleton's locked
facts. Every required code from the skeleton is woven in, so validation passes.
LLM mode is a marked TODO.
"""
from __future__ import annotations

from datagen.model import DocumentSkeleton, GeneratedDocument


def _location_clause(codes: list, shipment: str, incident: str) -> str:
    others = [c for c in codes if c not in (shipment, incident)]
    if not others:
        return ""
    return " Related entities: " + ", ".join(others) + "."


def _fmt(skel: DocumentSkeleton) -> str:
    meta = skel.metadata
    codes = skel.required_codes
    incident = meta.get("incident_code") or (codes[0] if codes else "the incident")
    shipment = meta.get("shipment_code") or "the shipment"
    delay = skel.required_numbers[0] if skel.required_numbers else "several"
    date = skel.required_dates[0] if skel.required_dates else "the reported date"
    cause = skel.cause_hint or "an operational issue"

    if skel.doc_type == "supplier_email":
        base = (f"Subject: delay notice - incident {incident}\n\n"
                f"Regarding shipment {shipment}: we note {cause}. The recorded delay is "
                f"{delay} days as of {date}.")
    elif skel.doc_type == "warehouse_report":
        base = (f"Warehouse report ({date}): incident {incident} records {cause} affecting "
                f"shipment {shipment}, contributing {delay} days of delay.")
    else:
        base = (f"Incident {incident}: shipment {shipment} was affected by {cause}, "
                f"resulting in a delay of {delay} days (recorded {date}).")

    return base + _location_clause(codes, shipment, incident)


def render(skeleton: DocumentSkeleton, use_llm: bool = False) -> GeneratedDocument:
    # TODO (LLM mode): rewrite _fmt(skeleton) via Ollama, constrained to the facts,
    # then validate; fall back to template on failure. Deterministic text for now.
    text = _fmt(skeleton)
    return GeneratedDocument(skeleton=skeleton, text=text, llm_generated=False, validation_passed=False)
