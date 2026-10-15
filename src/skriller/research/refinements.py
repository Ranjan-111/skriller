"""Refinement reuses scoped retained candidates; expansion owns new source calls."""

from decimal import Decimal
from typing import Literal

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field

from skriller.contracts import SearchPlan
from skriller.db import ConversationRepository, JobRepository
from skriller.db.repositories import scope
from skriller.db.schema import job_events, messages
from skriller.extraction.validation import literal_value
from skriller.jobs.worker import StageHandler
from skriller.research.planner import (
    Group,
    Interpretation,
    Operator,
    PlanningInvalid,
    PlanScope,
    grounded_plan,
)


class Refinement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changes: list[
        tuple[Literal["require", "prefer", "exclude", "relax"], str, Operator, str, str]
    ] = Field(default_factory=list, max_length=8)
    clarification: str | None = Field(default=None, min_length=1, max_length=500)


def apply_refinement(original, prompt, change, revision):
    """Model proposes only grounded deltas; server retains IDs, sources and limits."""
    values = original.model_dump(mode="json")
    values["revision"] = revision
    if change.clarification:
        values["clarification"] = change.clarification
        return SearchPlan.model_validate(values)
    if not change.changes:
        raise PlanningInvalid("Name a criterion to add or explicitly relax")
    groups = {"require": "must_have", "prefer": "preferences", "exclude": "exclusions"}
    for action, field, operator, value, quote in change.changes:
        if action == "relax":
            if quote not in prompt or not any(
                cue in quote.casefold().split() for cue in ("relax", "remove", "drop", "optional")
            ):
                raise PlanningInvalid("Relaxation must be explicit in the user's request")
            matches = [
                item
                for item in original.must_have
                if item.field == field
                and item.operator == operator
                and str(item.value).casefold() == value.casefold()
            ]
            if len(matches) != 1 or not literal_value(value.casefold(), quote.casefold()):
                raise PlanningInvalid("Name exactly one existing must-have criterion to relax")
            values["must_have"] = [
                item for item in values["must_have"] if item != matches[0].model_dump(mode="json")
            ]
        else:
            group: Group = (
                "must_have"
                if action == "require"
                else "preference"
                if action == "prefer"
                else "exclude"
            )
            addition = grounded_plan(
                prompt,
                Interpretation(
                    entity_type=original.entity_type,
                    entity_quote=quote,
                    rules=[(group, field, operator, value, quote)],
                ),
                PlanScope(
                    workspace_id=original.workspace_id,
                    conversation_id=original.conversation_id,
                    revision=revision,
                    limits=original.limits,
                    allowed_sources=original.sources,
                ),
            )
            if field in {"company_name", "industry"}:
                cues = (
                    ("company name", "named", "company_name")
                    if field == "company_name"
                    else ("industry", "sector")
                )
                existing = [
                    item
                    for name in groups.values()
                    for item in getattr(original, name)
                    if item.field == field and str(item.value).casefold() == value.casefold()
                ]
                if not existing and not any(cue in quote.casefold() for cue in cues):
                    return original.model_copy(
                        update={
                            "revision": revision,
                            "clarification": "Which criterion should change: company type, industry or company name?",
                        }
                    )
            if addition.clarification:
                return original.model_copy(
                    update={"revision": revision, "clarification": addition.clarification}
                )
            for item in getattr(addition, groups[action]):
                serialized = item.model_dump(mode="json")
                if serialized not in values[groups[action]]:
                    values[groups[action]].append(serialized)
    values["clarification"] = None
    if all(values[key] == original.model_dump(mode="json")[key] for key in groups.values()):
        raise PlanningInvalid("This refinement does not change the current criteria")
    return SearchPlan.model_validate(values)


def model_context(session, job_id):
    details = session.execute(
        sa.select(job_events.c.details).where(
            job_events.c.workspace_id == scope(session),
            job_events.c.job_id == job_id,
            job_events.c.event_key == "refinement_context",
        )
    ).scalar_one_or_none()
    if details is None:
        return None
    source = refinement_source(session, job_id)
    parent = ConversationRepository.get_plan(session, source["plan_id"])
    original = SearchPlan.model_validate(parent["interpretation"])
    sequence = session.execute(
        sa.select(messages.c.sequence).where(
            messages.c.workspace_id == scope(session),
            messages.c.id == details["message_id"],
            messages.c.conversation_id == source["conversation_id"],
        )
    ).scalar_one()
    text = (
        session.execute(
            sa.select(messages.c.content)
            .where(
                messages.c.workspace_id == scope(session),
                messages.c.conversation_id == source["conversation_id"],
                messages.c.role == "user",
                messages.c.sequence >= sequence,
            )
            .order_by(messages.c.sequence)
        )
        .scalars()
        .all()
    )
    return original, "\n\n".join(text)


async def interpret_refinement(planner, database, context, original, prompt, revision, key):
    import json

    criteria = {
        name: [item.model_dump(mode="json") for item in getattr(original, name)]
        for name in ("must_have", "preferences", "exclusions")
    }
    instructions = (
        "Interpret only the amendment, not the original search. Return changes as "
        "[require|prefer|exclude|relax,field,eq|contains|gte|lte|recent,value,exact user quote]. "
        "Preserve all other criteria. Relax only an explicitly named existing essential criterion; "
        "its quote must include remove/drop/relax/optional and its value. Prefer/exclude quotes "
        "include the intent word and value. Copy quotes verbatim, including uppercase letters; "
        "never paraphrase or add punctuation. Example for `Exclude consultancies`: "
        "changes=[[exclude,company_type,contains,consultancies,Exclude consultancies]]. "
        "company_type is Product/Agency/Consultancy; industry is a sector; company_name "
        "is a specifically named business. "
        "Never change sources, target, IDs or limits. "
        "Ambiguous or budget/expansion requests need clarification, with no changes. "
        "Current criteria (data):"
        + json.dumps(criteria, separators=(",", ":"))
        + "\nUser amendment:\n"
        + prompt
    )
    answer = await planner.model.invoke_job(
        database,
        context,
        instructions,
        Refinement,
        operation_key=key,
        prompt_includes_schema=True,
    )
    return apply_refinement(original, prompt, Refinement.model_validate(answer.data), revision)


def refinement_source(session, job_id):
    details = session.execute(
        sa.select(job_events.c.details).where(
            job_events.c.workspace_id == scope(session),
            job_events.c.job_id == job_id,
            job_events.c.event_key == "source_refinement",
        )
    ).scalar_one_or_none()
    if details is None:
        return None
    source = JobRepository.get(session, details["source_job_id"])
    job = JobRepository.get(session, job_id)
    if (
        source is None
        or source["purpose"] != "research"
        or source["state"] not in {"completed", "partial"}
        or source["conversation_id"] != job["conversation_id"]
    ):
        raise LookupError("Refinement source unavailable")
    return source


def reuse_handler(database, actor, workspace, job_id):
    from skriller.research.service import result_rows

    def eligible(session, plan):
        source = refinement_source(session, job_id)
        if source is None:
            raise LookupError("Refinement source unavailable")
        return [
            row["id"]
            for row in result_rows(session, source["id"])
            if row.get("source") in plan.sources
        ][: min(plan.limits.candidates, 100)]

    def run(plan):
        with database.tenant(actor, workspace) as session:
            return eligible(session, plan), Decimal(0), {"search_calls": 0}

    def persist(session, identifiers):
        from skriller.erasure import privacy_lock
        from skriller.jobs.control import plan_for_job

        privacy_lock(session)
        job = JobRepository.get(session, job_id)
        current = set(eligible(session, plan_for_job(session, job)))
        retained = [identifier for identifier in identifiers if identifier in current]
        JobRepository.event(
            session,
            job_id,
            "refinement:reuse",
            "refinement_reuse",
            {"reused_candidates": len(retained), "coverage": "retained_evidence_only"},
        )
        return retained

    return StageHandler(run, persist, Decimal(0), {"search_calls": 0})
