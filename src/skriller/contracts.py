"""Bounded product contracts; source engines never receive free-form execution code."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Source = Literal[
    "linkedin", "reddit", "web", "github", "rss", "youtube", "x", "instagram", "facebook"
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Criterion(Contract):
    field: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    operator: Literal["eq", "gte", "lte", "contains", "in", "recent"]
    value: str | int | float | bool | list[str]

    @model_validator(mode="after")
    def operator_value(self):
        if self.operator == "in" and not isinstance(self.value, list):
            raise ValueError("Membership requires a list of values")
        if self.operator == "contains" and not isinstance(self.value, str):
            raise ValueError("Contains requires text")
        if self.operator in {"gte", "lte", "recent"} and (
            isinstance(self.value, bool) or not isinstance(self.value, (int, float))
        ):
            raise ValueError("Comparison requires a numeric value")
        if self.operator == "recent" and self.value < 0:
            raise ValueError("Recency cannot be negative")
        if self.operator == "eq" and isinstance(self.value, list):
            raise ValueError("Equality requires a scalar value")
        return self

    @field_validator("value")
    @classmethod
    def bound_value(cls, value):
        if isinstance(value, str) and len(value) > 500:
            raise ValueError("Criterion text too long")
        if isinstance(value, list) and (len(value) > 20 or any(len(item) > 100 for item in value)):
            raise ValueError("Criterion list too large")
        return value


class Limits(Contract):
    result_limit: int = Field(default=25, ge=1, le=100)
    search_calls: int = Field(default=20, ge=0, le=20)
    candidates: int = Field(default=300, ge=1, le=300)
    fetch_attempts: int = Field(default=200, ge=0, le=200)
    llm_calls: int = Field(default=40, ge=0, le=40)
    token_cap: int = Field(default=100_000, ge=0, le=100_000)
    deadline_seconds: int = Field(default=1200, ge=1, le=1200)
    currency_cap: Decimal = Field(
        default=Decimal(0), ge=0, le=Decimal(100), max_digits=12, decimal_places=6
    )


def default_sources() -> list[Source]:
    return ["linkedin", "web"]


class SearchPlan(Contract):
    schema_version: Literal[1] = 1
    workspace_id: UUID
    conversation_id: UUID
    revision: int = Field(ge=1)
    entity_type: Literal["person", "company", "creator", "discussion"]
    must_have: list[Criterion] = Field(default_factory=list, max_length=20)
    preferences: list[Criterion] = Field(default_factory=list, max_length=20)
    exclusions: list[Criterion] = Field(default_factory=list, max_length=20)
    requested_fields: list[str] = Field(default_factory=list, max_length=30)
    sources: list[Source] = Field(default_factory=default_sources, max_length=9)
    freshness_days: int | None = Field(default=None, ge=1, le=3650)
    unsupported_criteria: list[str] = Field(default_factory=list, max_length=20)
    clarification: str | None = Field(default=None, max_length=1000)
    limits: Limits = Field(default_factory=Limits)

    @field_validator("requested_fields")
    @classmethod
    def safe_field_names(cls, fields):
        import re

        if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", name) for name in fields):
            raise ValueError("Unsafe field name")
        return fields

    @field_validator("sources")
    @classmethod
    def unique_sources(cls, sources):
        if len(set(sources)) != len(sources):
            raise ValueError("Duplicate source preferences")
        return sources


class Capability(Contract):
    source: Source
    operation: Literal["discover", "read", "analytics"]
    engineering_status: Literal["planned", "implemented", "tested"]
    operational_status: Literal[
        "experimental",
        "available",
        "needs_connection",
        "needs_access_agreement",
        "rate_limited",
        "unavailable",
    ]
    access_route: str = Field(max_length=200)
    auth_kind: Literal["none", "oauth", "session", "api_key"]
    version: str = Field(max_length=100)
    allowed_fields: list[str] = Field(default_factory=list, max_length=50)


class ExecutionContext(Contract):
    workspace_id: UUID
    job_id: UUID
    actor_id: str = Field(min_length=1, max_length=128)
    plan_revision: int = Field(ge=1)
    deadline: datetime
    connection_ref: UUID | None = None
    reservation_id: UUID | None = None
    attempt_budget: int = Field(ge=0, le=200)

    @field_validator("deadline")
    @classmethod
    def timezone_required(cls, deadline):
        if deadline.tzinfo is None:
            raise ValueError("Deadline requires timezone")
        return deadline


class Failure(Contract):
    code: Literal[
        "auth_required",
        "auth_expired",
        "access_denied",
        "challenge_detected",
        "rate_limited",
        "quota_exhausted",
        "not_found",
        "unsupported_operation",
        "source_unavailable",
        "schema_invalid",
        "evidence_missing",
        "ambiguous_match",
        "deadline_exceeded",
        "budget_exhausted",
        "cancelled",
    ]
    message: str = Field(max_length=500)
    retry_after_seconds: int | None = Field(default=None, ge=0, le=86400)


JobState = Literal[
    "planned",
    "queued",
    "running",
    "waiting_for_connection",
    "paused",
    "completed",
    "partial",
    "failed",
    "cancelled",
]


class JobSnapshot(Contract):
    id: UUID
    workspace_id: UUID
    state: JobState
    stage: str | None
    version: int = Field(ge=0)
    terminal_reason: str | None = None


class ProgressEvent(Contract):
    kind: str
    details: dict
