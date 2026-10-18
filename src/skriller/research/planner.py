"""Detached, grounded prompt interpretation; initial-job routing is not wired here."""

import re
from typing import Annotated, Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from skriller.contracts import Criterion, ExecutionContext, Limits, SearchPlan, Source
from skriller.db import ConversationRepository
from skriller.extraction.groq import structured_model
from skriller.extraction.models import LocalStructuredModel
from skriller.extraction.validation import literal_value
from skriller.jobs.budget import locked_job
from skriller.jobs.control import remaining_seconds
from skriller.settings import Settings

Group = Literal["must_have", "preference", "exclude"]
Operator = Literal["eq", "contains", "gte", "lte", "recent"]
# Compact tuple schemas keep format instructions inside the local context bound.
IntentText = Annotated[str, Field(min_length=1, max_length=500)]
Rule = tuple[Group, IntentText, Operator, IntentText, IntentText]
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
    "name": ("name", "names"),
    "source_url": ("url", "urls", "link", "links", "source", "sources"),
    "company_name": ("company", "companies"),
    "founder_name": ("founder", "founders"),
    "location": ("location", "locations", "city", "cities", "where"),
    "hiring_role": ("hiring",),
    "employee_count": ("employee", "employees", "headcount"),
    "public_contact": ("public contact",),
    "private_email": ("private email",),
    "private_phone": ("private phone",),
    "password": ("password",),
    "session_cookie": ("cookie",),
}


class Interpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: Literal["person", "company", "creator", "discussion"]
    entity_quote: IntentText
    rules: list[Rule] = Field(default_factory=list, max_length=12)
    sources: list[tuple[Source, IntentText]] = Field(default_factory=list, max_length=9)
    fields: list[tuple[IntentText, IntentText]] = Field(default_factory=list, max_length=12)
    unsupported: list[IntentText] = Field(default_factory=list, max_length=8)
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
    geography_answers = {
        "company headquarters": "company_location",
        "company location": "company_location",
        "person location": "person_location",
        "person's location": "person_location",
        "the person's location": "person_location",
    }
    # Only an exact subsequent user clarification resolves this ambiguity; a
    # model's guess or a phrase inside an unrelated sentence does not.
    geography_choice = next(
        (
            geography_answers[part.strip().casefold()]
            for part in reversed(prompt.split("\n\n")[1:])
            if part.strip().casefold() in geography_answers
        ),
        None,
    )
    for value in unsupported:
        quote(value)
    for group, field, operator, value, evidence in interpretation.rules:
        original = quote(evidence)
        if field not in FIELDS:
            raise PlanningInvalid(
                "Interpretation contains an unsupported criterion", reason="unsupported_criterion"
            )
        numeric = operator in {"gte", "lte", "recent"}
        if numeric:
            try:
                grounded = (
                    literal_value(int(value), original)
                    if value.lstrip("+-").isdigit()
                    else literal_value(float(value), original)
                )
            except ValueError:
                grounded = False
        else:
            grounded = literal_value(value.casefold(), original)
            # Explicit grammatical forms only, never arbitrary substring/stem matching.
            aliases = {
                ("role", "founder"): "founders",
                ("role", "engineer"): "engineers",
                ("company_type", "agency"): "agencies",
            }
            alias = aliases.get((field, value.casefold()))
            grounded = grounded or bool(alias and literal_value(alias, original))
        if not grounded:
            raise PlanningInvalid(
                "Interpretation contains an ungrounded criterion value", reason="ungrounded_value"
            )
        comparison_cues = {
            "gte": r"\b(?:at\s+least|minimum(?:\s+of)?|no\s+fewer\s+than)\b",
            "lte": r"\b(?:at\s+most|maximum(?:\s+of)?|no\s+more\s+than)\b",
            "recent": r"\b(?:last|past|within)\b",
        }
        if numeric:
            # A broad quote can contain several bounds. Bind this comparison
            # to its own exact numeric token, rather than any number in it.
            bound = comparison_cues[operator] + r"\s+" + re.escape(value) + r"(?![\w.,])"
            if operator == "recent":
                bound += r"\s+days?\b"
            if not re.search(bound, original):
                raise PlanningInvalid("Numeric comparison must be explicitly grounded")
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
        ambiguous_person_company = (
            interpretation.entity_type == "person"
            and re.search(r"\bat\s+companies\s+in\b", prompt, re.IGNORECASE)
            and (
                field == "company_location"
                and "headquartered" not in original
                and geography_choice != "company_location"
                or field == "person_location"
                and not re.search(r"\b(?:based|located|living)\s+in\b", original)
                and geography_choice != "person_location"
            )
        )
        if field == "location" or ambiguous_person_company:
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
        if field == "role" and operator == "contains" and isinstance(parsed, str):
            # Normalize only the grammatical forms already admitted above. A
            # plural user request must still match a saved singular job title.
            parsed = {"founders": "founder", "engineers": "engineer"}.get(parsed.casefold(), parsed)
        criterion = Criterion(field=field, operator=operator, value=parsed)
        groups[group].append(criterion)
    selected: list[Source] = []
    for source, evidence in interpretation.sources:
        if not literal_value(source.casefold(), quote(evidence)):
            raise PlanningInvalid("A source preference must be explicitly requested")
        if source not in scope.allowed_sources:
            unsupported.append(evidence)
        elif source not in selected:
            selected.append(source)
    requested = list(scope.default_fields)
    for field, evidence in interpretation.fields:
        original = quote(evidence)
        if field not in FIELD_WORDS or not any(
            literal_value(word, original) for word in FIELD_WORDS[field]
        ):
            raise PlanningInvalid("A requested field must be explicitly grounded")
        if field in PRIVATE_FIELDS:
            unsupported.append(evidence)
        elif field not in PUBLIC_FIELDS:
            raise PlanningInvalid("Unsupported requested field")
        elif field not in requested:
            requested.append(field)
    # The model may omit an explicit material constraint while still returning
    # schema-valid JSON. Pause rather than execute a silently weaker plan.
    cues = [
        (r"\b(?:exclude|avoid|without)\b", bool(groups["exclude"]), "exclusion"),
        (r"\b(?:prefer|ideally|prioriti[sz]e)\b", bool(groups["preference"]), "preference"),
        (
            r"\bheadquartered\b",
            any(rule.field == "company_location" for rule in groups["must_have"]),
            "company headquarters",
        ),
        (
            r"\b(?:founders|people|persons)\s+based\s+in\b",
            any(rule.field == "person_location" for rule in groups["must_have"]),
            "person location",
        ),
        (
            r"\b(?:at\s+least|minimum(?:\s+of)?|no\s+fewer\s+than)\s+\d+\s+employees\b",
            any(
                rule.field == "employee_count" and rule.operator == "gte"
                for rule in groups["must_have"]
            ),
            "minimum employee count",
        ),
        (
            r"\b(?:at\s+most|maximum(?:\s+of)?|no\s+more\s+than)\s+\d+\s+employees\b",
            any(
                rule.field == "employee_count" and rule.operator == "lte"
                for rule in groups["must_have"]
            ),
            "maximum employee count",
        ),
        (
            r"\bin\s+(?:the\s+)?[A-Za-z][A-Za-z -]{0,80}\s+industry\b",
            any(rule.field == "industry" for rules in groups.values() for rule in rules),
            "industry",
        ),
    ]
    missing = [
        name
        for pattern, present, name in cues
        if re.search(pattern, prompt, re.IGNORECASE) and not present
    ]
    represented_sources = {source for source, _ in interpretation.sources}
    for source in get_args(Source):
        # X/web are common words outside source preferences. Require a source
        # preposition for these ambiguous names; other platform names are exact.
        pattern = (
            r"\b(?:on|from|using|across)\s+(?:the\s+)?" + source + r"\b"
            if source in {"x", "web"}
            else r"\b" + source + r"\b"
        )
        if (
            re.search(pattern, prompt, re.IGNORECASE)
            and source not in represented_sources
            and not any(re.search(pattern, value, re.IGNORECASE) for value in unsupported)
        ):
            missing.append(source + " source selection")
    if missing:
        clarification = clarification or "Please confirm the requested " + ", ".join(missing) + "."
    for field in PRIVATE_FIELDS:
        for phrase in FIELD_WORDS[field]:
            match = re.search(r"\b" + re.escape(phrase) + r"\b", prompt, re.IGNORECASE)
            if match:
                unsupported.append(match.group())
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
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 3500:
            raise PlanningInvalid("Planning context must contain 1–3,500 characters")
        instructions = (
            "Interpret intent only. entity_type is what the user wants to find: founders means person; "
            "entity_quote is the exact nonempty phrase naming that target. Rules are "
            "[must_have|preference|exclude,field,operator,value,exact quote] and are only for "
            "qualification criteria, never output fields. Fields are only requested result attributes. "
            "Allowed rule fields=role,industry,company_type,company_name,person_location,company_location,"
            "hiring_role,employee_count,location. If location could refer to either a person or their "
            "company, emit a location rule; the server will ask for clarification and remove that filter. "
            "Sources/fields=[name,exact quote]. No inferred preferences. Private fields unsupported. "
            "Every quote must be a nonempty verbatim substring of the user text, including case. "
            "Preference/exclusion quotes include their intent word (Prefer/Exclude) and value. "
            "Example: for `Find founders at companies in London.`, return entity_type=person, "
            "entity_quote=`founders`, rules=[[must_have,location,eq,London,companies in London]], "
            "and empty sources, fields, and unsupported lists. User:\n" + prompt
        )
        answer = await self.model.invoke_job(
            database,
            context,
            instructions,
            Interpretation,
            operation_key=operation_key,
            prompt_includes_schema=True,
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
