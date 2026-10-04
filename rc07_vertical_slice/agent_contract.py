from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, ConfigDict, field_validator


class Outcome(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ClaimType(str, Enum):
    ENTITY_FACT = "ENTITY_FACT"
    NUMERIC = "NUMERIC"
    RELATIONSHIP = "RELATIONSHIP"
    TREND = "TREND"
    CAUSAL = "CAUSAL"
    COMPARATIVE = "COMPARATIVE"
    AGGREGATE = "AGGREGATE"  # a value read directly from an aggregate SQL result (text-to-SQL)


class SupportStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"


class SourceType(str, Enum):
    SQL = "SQL"
    DOCUMENT = "DOCUMENT"
    GRAPH = "GRAPH"


class Relevance(str, Enum):
    DIRECT = "DIRECT"
    CONTEXTUAL = "CONTEXTUAL"
    CONTRADICTORY = "CONTRADICTORY"


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    source_type: SourceType
    source_ref: str
    locator: dict[str, Any]
    fact: str
    relevance: Relevance


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    text: str
    claim_type: ClaimType
    support_status: SupportStatus
    evidence_ids: list[str] = Field(min_length=1)


class ToolTraceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int
    tool_call_id: str
    tool: Literal["query_database", "search_documents", "graph_query", "verify_evidence"]
    purpose: str
    status: Literal["SUCCESS", "ERROR"]
    input: dict[str, Any]
    output_refs: list[str] = Field(default_factory=list)


class VerificationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str
    type: str
    claim_id: str | None = None
    status: Literal["PASS", "FAIL"]
    detail: str | None = None


class Verification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["PASSED", "FAILED"]
    checks: list[VerificationCheck]


class Timing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_ms: int = 0
    tool_ms: int = 0
    llm_ms: int = 0


class AgentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["agent_response_v1"] = "agent_response_v1"
    run_id: str
    question: str
    outcome: Outcome
    answer: str
    claims: list[Claim]
    evidence: list[Evidence]
    tool_trace: list[ToolTraceEntry]
    verification: Verification
    timing: Timing = Timing()

    @field_validator("claims")
    @classmethod
    def unique_claim_ids(cls, value: list[Claim]) -> list[Claim]:
        ids = [c.claim_id for c in value]
        if len(ids) != len(set(ids)):
            raise ValueError("claim_id values must be unique")
        return value

    @field_validator("evidence")
    @classmethod
    def unique_evidence_ids(cls, value: list[Evidence]) -> list[Evidence]:
        ids = [e.evidence_id for e in value]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence_id values must be unique")
        return value
