"""
STAGE 11a — turn skeletons into natural prose via Ollama, OR pass through skeleton
text when use_llm is False (--no-llm). Prose is the ONLY non-deterministic projection;
it is validated (docs/validate.py) and regenerable, never a source of truth.

Hard-constraint prompt: use ONLY the skeleton's facts; invent no codes/dates/numbers.
"""
from __future__ import annotations
import datagen.config as config
from datagen.model import DocumentSkeleton, GeneratedDocument


def render(skeleton: DocumentSkeleton, use_llm: bool = True) -> GeneratedDocument:
    """Generate (or passthrough) text for one skeleton, then mark validation status."""
    raise NotImplementedError
