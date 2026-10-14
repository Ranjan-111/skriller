"""Detached, grounded prompt interpretation; initial-job routing is not wired here."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from skriller.contracts import Criterion, ExecutionContext, Limits, SearchPlan, Source
from skriller.db import ConversationRepository
from skriller.extraction.groq import structured_model
from skriller.extraction.models import LocalStructuredModel
from skriller.jobs.budget import locked_job
from skriller.jobs.control import remaining_seconds
from skriller.settings import Settings

Group = Literal["must_have", "preference", "exclude"]
Operator = Literal["eq", "contains", "gte", "lte", "recent"]
# Compact tuple schemas keep format instructions inside the local context bound.
Rule = tuple[Group, str, Operator, str, str]
FIELDS = {
    "role",
    "industry",
    "company_type",
    "company_name",
    "person_location",
    "company_location",
    "hiring_role",
    "employee_count",
    "location",
}
PUBLIC_FIELDS = {
    "name",
    "source_url",
    "company_name",
    "founder_name",
    "location",
    "hiring_role",
    "employee_count",
    "public_contact",
}
PRIVATE_FIELDS = {"private_email", "private_phone", "password", "session_cookie"}
FIELD_WORDS = {
    "name": ("name",),
    "source_url": ("url", "link", "source"),
    "company_name": ("company", "companies"),
    "founder_name": ("founder",),
    "location": ("location", "city", "where"),
    "hiring_role": ("hiring",),
    "employee_count": ("employee", "headcount"),
    "public_contact": ("public contact",),
    "private_email": ("private email",),
    "private_phone": ("private phone",),
    "password": ("password",),
    "session_cookie": ("cookie",),
}


class Interpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: Literal["person", "company", "creator", "discussion"]
    entity_quote: str
    rules: list[Rule] = Field(default_factory=list, max_length=12)
    sources: list[tuple[Source, str]] = Field(default_factory=list, max_length=9)
    fields: list[tuple[str, str]] = Field(default_factory=list, max_length=12)
    unsupported: list[str] = Field(default_factory=list, max_length=8)
    clarification: str | None = None

    @model_validator(mode="after")
    def bound_text(self):
        text = [
            self.entity_quote,
            *(part for rule in self.rules for part in rule),
            *(part for pair in self.sources + self.fields for part in pair),
            *self.unsupported,
        ]
        if self.clarification is not None:
            text.append(self.clarification)
        if any(not value.strip() or len(value) > 500 for value in text):
            raise ValueError("Interpretation text must be nonempty and bounded")
        return self


class PlanScope(BaseModel):
    """Trusted server choices, never included in the model's output schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    workspace_id: UUID
    conversation_id: UUID
    revision: int = Field(ge=1)
    limits: Limits
    allowed_sources: list[Source] = Field(min_length=1, max_length=9)
    default_fields: list[str] = Field(default_factory=lambda: ["name", "source_url"], max_length=12)

    @model_validator(mode="after")
    def server_choices(self):
        if len(set(self.allowed_sources)) != len(self.allowed_sources):
            raise ValueError("Duplicate server source selection")
        if not set(self.default_fields) <= PUBLIC_FIELDS:
            raise ValueError("Unsupported server field selection")
        return self


class PlanningInvalid(ValueError):
    def __init__(
        self,
        message: str,
        *,
        reason: Literal[
            "interpretation_rejected",
            "ungrounded_quote",
            "unsupported_criterion",
            "ungrounded_value",
            "preference_missing_cue",
            "exclusion_missing_cue",
        ] = "interpretation_rejected",
    ):
        self.reason = reason
        super().__init__(message)


def grounded_plan(prompt: str, interpretation: Interpretation, scope: PlanScope) -> SearchPlan:
    """Source quotes prevent unsupported additions; they are not semantic accuracy proof."""

    def quote(value):
        if value not in prompt:
            raise PlanningInvalid(
                "Interpretation contains intent not grounded in the user prompt",
                reason="ungrounded_quote",
            )
        return value.casefold()

    quote(interpretation.entity_quote)
    groups: dict[str, list[Criterion]] = {"must_have": [], "preference": [], "exclude": []}
    clarification = interpretation.clarification
    unsupported = list(interpretation.unsupported)
    for value in unsupported:
        quote(value)
    for group, field, operator, value, evidence in interpretation.rules:
        original = quote(evidence)
        if field not in FIELDS:
            raise PlanningInvalid(
                "Interpretation contains an unsupported criterion", reason="unsupported_criterion"
            )
        if value.casefold() not in original:
            raise PlanningInvalid(
                "Interpretation contains an ungrounded criterion value", reason="ungrounded_value"
            )
        if group == "preference" and not any(
            word in original
            for word in ("prefer", "prioritis", "prioritiz", "ideally", "nice to have")
        ):
            raise PlanningInvalid(
                "A preference must be explicitly requested", reason="preference_missing_cue"
            )
        if group == "exclude" and not any(
            word in original for word in ("exclude", "avoid", "without", "not ", "except")
        ):
            raise PlanningInvalid(
                "An exclusion must be explicitly requested", reason="exclusion_missing_cue"
            )
        if field == "location":
            clarification = (
                clarification or "Should location refer to the person or the company headquarters?"
            )
            continue
        parsed: str | float = value
        if operator in {"gte", "lte", "recent"}:
            try:
                parsed = float(value)
            except ValueError:
                raise PlanningInvalid("Numeric criterion needs an explicit numeric value") from None
        criterion = Criterion(field=field, operator=operator, value=parsed)
        groups[group].append(criterion)
    selected: list[Source] = []
    for source, evidence in interpretation.sources:
        if source.casefold() not in quote(evidence):
            raise PlanningInvalid("A source preference must be explicitly requested")
        if source not in scope.allowed_sources:
            unsupported.append(evidence)
        elif source not in selected:
            selected.append(source)
    requested = list(scope.default_fields)
    for field, evidence in interpretation.fields:
        original = quote(evidence)
        if field not in FIELD_WORDS or not any(word in original for word in FIELD_WORDS[field]):
            raise PlanningInvalid("A requested field must be explicitly grounded")
        if field in PRIVATE_FIELDS:
            unsupported.append(evidence)
        elif field not in PUBLIC_FIELDS:
            raise PlanningInvalid("Unsupported requested field")
        elif field not in requested:
            requested.append(field)
    # Every identity, revision and spending limit is injected by the server.
    return SearchPlan(
        workspace_id=scope.workspace_id,
        conversation_id=scope.conversation_id,
        revision=scope.revision,
        entity_type=interpretation.entity_type,
        must_have=groups["must_have"],
        preferences=groups["preference"],
        exclusions=groups["exclude"],
        sources=selected or list(scope.allowed_sources),
        requested_fields=requested,
        unsupported_criteria=list(dict.fromkeys(unsupported)),
        clarification=clarification,
        limits=Limits.model_validate(scope.limits.model_dump()),
    )


class PromptPlanner:
    def __init__(
        self, model: LocalStructuredModel | None = None, *, settings: Settings | None = None
    ):
        self._owns_model = model is None
        self.model = model if model is not None else structured_model(settings or Settings())

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        await self.aclose()

    async def aclose(self):
        """Configured clients are planner-owned; injected clients stay caller-owned."""
        if self._owns_model and hasattr(self.model, "aclose"):
            await self.model.aclose()

    async def interpret(
        self,
        database,
        context: ExecutionContext,
        prompt: str,
        scope: PlanScope,
        *,
        operation_key: str,
    ) -> SearchPlan:
        if scope.workspace_id != context.workspace_id:
            raise PlanningInvalid("Planning workspace does not match execution scope")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 1500:
            raise PlanningInvalid("Planning prompt must contain 1–1500 characters")
        instructions = (
            "Interpret intent only. Rules=[must_have|preference|exclude,field,operator,value,exact quote]. "
            "Fields=role,industry,company_type,company_name,person_location,company_location,"
            "hiring_role,employee_count,location. Ambiguous geography uses location+clarification. "
            "Sources/fields=[name,quote]. No inferred preferences. Private fields unsupported. "
            "Quotes are verbatim, including case. Preference/exclusion quotes include their intent "
            "word (Prefer/Exclude) and value. User:\n" + prompt
        )
        answer = await self.model.invoke_job(
            database, context, instructions, Interpretation, operation_key=operation_key
        )
        return grounded_plan(prompt, Interpretation.model_validate(answer.data), scope)


def persist_revision(database, context: ExecutionContext, plan: SearchPlan, *, parent_id: str):
    """Persist only a verified successor to the same latest immutable planning parent."""
    if plan.workspace_id != context.workspace_id or plan.revision != context.plan_revision + 1:
        raise PlanningInvalid("Planning revision or workspace mismatch")
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        job = locked_job(session, str(context.job_id))
        if job["state"] not in {"queued", "running"} or remaining_seconds(session, job) <= 0:
            raise PlanningInvalid("Planning job no longer permits successor writes")
        parent = ConversationRepository.get_plan(session, parent_id)
        if (
            parent is None
            or job["plan_id"] != parent_id
            or parent["revision"] != context.plan_revision
            or str(plan.conversation_id) != parent["conversation_id"]
        ):
            raise PlanningInvalid("Planning parent does not match the execution job")
        row = ConversationRepository.revise_plan(
            session, str(plan.conversation_id), plan.model_dump(mode="json"), parent_id=parent_id
        )
        if row["revision"] != plan.revision:
            raise PlanningInvalid("Persisted planning revision mismatch")
        return row
