from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


MAX_TASK_CHARS = 12_000
MAX_OUTPUT_CHARS = 120_000
MAX_CANDIDATES = 32
MAX_CITATIONS = 32


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EvidenceState(str, Enum):
    PASS = "PASS"  # nosec B105 -- protocol state label, not a credential
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


class ProbeResult(StrictModel):
    probe: str
    state: EvidenceState
    score: float | None = Field(default=None, ge=0, le=1)
    reason: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class TrustSnapshotRequest(StrictModel):
    service_id: str = Field(min_length=1, max_length=200)
    task_type: str = Field(default="general", min_length=1, max_length=100)


class Assertion(StrictModel):
    path: str = Field(min_length=1, max_length=500)
    op: Literal["eq", "ne", "contains", "gte", "lte", "exists"]
    value: Any | None = None


class IndependentCheck(StrictModel):
    probe: str = Field(min_length=1, max_length=100)
    state: EvidenceState
    score: float | None = Field(default=None, ge=0, le=1)
    reason: str = Field(min_length=1, max_length=2000)
    evidence: dict[str, Any] = Field(default_factory=dict)


class DeliveryVerificationRequest(StrictModel):
    delivery_id: str = Field(min_length=1, max_length=200)
    provider_id: str = Field(min_length=1, max_length=200)
    task: str = Field(min_length=1, max_length=MAX_TASK_CHARS)
    task_type: str = Field(default="general", min_length=1, max_length=100)
    output: Any
    expected_schema: dict[str, Any] | None = None
    assertions: list[Assertion] = Field(default_factory=list, max_length=64)
    cited_urls: list[HttpUrl] = Field(default_factory=list, max_length=MAX_CITATIONS)
    independent_checks: list[IndependentCheck] = Field(default_factory=list, max_length=16)

    @field_validator("output")
    @classmethod
    def output_must_be_bounded(cls, value: Any) -> Any:
        # Avoid allowing a caller to turn a verifier call into unbounded memory work.
        rendered = repr(value)
        if len(rendered) > MAX_OUTPUT_CHARS:
            raise ValueError(f"output exceeds {MAX_OUTPUT_CHARS} characters")
        return value


class CandidateRequest(StrictModel):
    service_id: str = Field(min_length=1, max_length=200)
    price_credits: int = Field(ge=0, le=100)
    task_fit: float = Field(default=0.5, ge=0, le=1)
    latency_ms: int | None = Field(default=None, ge=0, le=300_000)


class CandidateScore(StrictModel):
    service_id: str
    price_credits: int
    trust_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    task_fit: float = Field(ge=0, le=1)
    latency_ms: int = Field(ge=0)
    observations: int = Field(ge=0)


class BestExecutionRequest(StrictModel):
    task: str = Field(min_length=1, max_length=MAX_TASK_CHARS)
    task_type: str = Field(default="general", min_length=1, max_length=100)
    budget_credits: int = Field(gt=0, le=100)
    candidates: list[CandidateRequest] = Field(min_length=1, max_length=MAX_CANDIDATES)
    mode: Literal["safe", "explore"] = "safe"

    @model_validator(mode="after")
    def candidates_must_be_unique(self):
        ids = [candidate.service_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate service_id values must be unique")
        return self


class GrantEnvelope(StrictModel):
    actor: str
    resource: str
    action: str
    purpose: str
    max_uses: int = Field(default=1, ge=1)
