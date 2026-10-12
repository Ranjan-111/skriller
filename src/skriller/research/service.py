"""Bounded search discovery, using copied engines through existing adapters.

This initial executor treats the prompt as a search objective. It does not claim
semantic qualification, page extraction, contact verification or a full planner.
"""

import asyncio
from dataclasses import replace
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from skriller.connectors.candidates import deduplicate
from skriller.connectors.search import ExaKeylessSearch, SearchUnavailable
from skriller.db import ConversationRepository, JobRepository, ResearchRepository
from skriller.db.repositories import scope
from skriller.db.schema import attempts, entities, messages
from skriller.jobs.control import permit_call
from skriller.jobs.outbox import CeleryPublisher, DispatchScope, OutboxDispatcher
from skriller.jobs.state import TERMINAL_STATES, finish
from skriller.jobs.worker import CheckpointWorker, StageHandler, TaskIdentity

DOMAINS = {
    "linkedin": ("linkedin.com",),
    "reddit": ("reddit.com",),
    "github": ("github.com",),
    "youtube": ("youtube.com",),
    "x": ("x.com", "twitter.com"),
    "instagram": ("instagram.com",),
    "facebook": ("facebook.com",),
    "web": (),
    "rss": (),
}
LIMITATIONS = [
    "Search snippets only: matching criteria, identities and contacts are unverified.",
    "Public indexed results do not grant access to private or authenticated platform content.",
    "The free provider returns at most 10 results per source; pagination is unavailable.",
    "The prompt is used as a search objective; structured semantic qualification is pending.",
]


def actor_workspaces(database, actor):
    with Session(database.engine) as session, session.begin():
        database._assert_application_role(session)
        session.execute(
            sa.text("SELECT set_config('app.actor_id', :actor, true)"), {"actor": actor}
        )
        return [
            dict(row)
            for row in session.execute(sa.text("SELECT * FROM actor_workspaces()")).mappings()
        ]


def personal_workspace(database, actor):
    with Session(database.engine) as session, session.begin():
        database._assert_application_role(session)
        session.execute(
            sa.text("SELECT set_config('app.actor_id', :actor, true)"), {"actor": actor}
        )
        return dict(
            session.execute(sa.text("SELECT * FROM get_or_create_personal_workspace()"))
            .mappings()
            .one()
        )


def locate(database, actor, repository, identifier, workspace=None):
    scopes = (
        [str(workspace)]
        if workspace
        else [str(row["id"]) for row in actor_workspaces(database, actor)]
    )
    for workspace_id in scopes:
        with database.tenant(actor, workspace_id) as session:
            row = repository.get(session, str(identifier))
            if row is not None:
                return workspace_id, dict(row)
    raise LookupError("Resource unavailable")


def result_rows(session, job_id):
    refs = (
        session.execute(
            sa.select(attempts.c.result_entity_ids).where(
                attempts.c.workspace_id == scope(session),
                attempts.c.job_id == job_id,
                attempts.c.state == "succeeded",
            )
        )
        .scalars()
        .all()
    )
    ids = list(dict.fromkeys(identifier for batch in refs for identifier in batch))
    if not ids:
        return []
    rows = (
        session.execute(
            sa.select(entities).where(
                entities.c.workspace_id == scope(session),
                entities.c.id.in_(ids),
            )
        )
        .mappings()
        .all()
    )
    by_id = {row["id"]: row for row in rows}
    return [
        {
            "id": identifier,
            "title": by_id[identifier]["display_name"],
            **by_id[identifier]["attributes"],
        }
        for identifier in ids
        if identifier in by_id
    ]


def workspace_id_for_job(database, actor, job_id):
    return locate(database, actor, JobRepository, job_id)[0]


def discovery_handler(database, actor, job_id, provider=None):
    provider = provider or ExaKeylessSearch()
    with database.tenant(actor, workspace_id_for_job(database, actor, job_id)) as session:
        job = JobRepository.get(session, job_id)
        result_limit = ConversationRepository.get_plan(session, job["plan_id"])["interpretation"][
            "limits"
        ]["result_limit"]

    # All source input is loaded with the task's authenticated tenant scope.
    def run(plan, timeout_seconds=110):
        with database.tenant(actor, str(plan.workspace_id)) as session:
            prompt = session.execute(
                sa.select(messages.c.content)
                .where(
                    messages.c.workspace_id == scope(session),
                    messages.c.conversation_id == str(plan.conversation_id),
                    messages.c.role == "user",
                )
                .order_by(messages.c.sequence.desc())
                .limit(1)
            ).scalar_one()

        async def discover():
            data, calls = [], 0
            loop = asyncio.get_running_loop()
            # Leave checkpoint time inside the committed attempt/capacity lease.
            window = timeout_seconds - 1 if timeout_seconds > 1 else timeout_seconds * 0.8
            end = loop.time() + max(0, window)
            stop_reason = None
            for source in plan.sources:
                entry = {"source": source, "page": None, "error": stop_reason, "failure": None}
                if stop_reason:
                    data.append(entry)
                    continue
                with database.tenant(actor, str(plan.workspace_id)) as session:
                    allowed = permit_call(session, job_id)
                time_left = min(allowed, end - loop.time())
                if time_left <= 0:
                    stop_reason = "deadline_exceeded" if allowed else "cancelled"
                    entry["error"] = stop_reason
                    data.append(entry)
                    continue
                domains = DOMAINS[source]
                query = prompt
                if domains:
                    query += " " + " OR ".join(f"site:{domain}" for domain in domains)
                calls += 1
                try:
                    async with asyncio.timeout(time_left):
                        entry["page"] = await provider.search(
                            query[:2000],
                            objective=prompt,
                            limit=min(plan.limits.result_limit, 10),
                            domains=domains,
                        )
                except SearchUnavailable as exc:
                    entry["error"] = exc.failure.code
                    entry["failure"] = exc.failure
                    if exc.failure.code == "rate_limited":
                        stop_reason = "rate_limited"
                except TimeoutError:
                    entry["error"] = stop_reason = "deadline_exceeded"
                data.append(entry)
            return data, calls

        data, calls = asyncio.run(discover())
        return data, Decimal(0), {"search_calls": calls}

    def persist(session, data):
        ids = []
        failures = [
            {"source": entry["source"], "code": entry["error"]} for entry in data if entry["error"]
        ]
        pages = [(entry["source"], entry["page"]) for entry in data if entry["page"] is not None]
        for candidate in deduplicate(pages, limit=result_limit):
            hit = candidate.hit
            origin = candidate.provenance[0]
            record = ResearchRepository.entity(
                session,
                "other",
                hit.title,
                canonical_key=f"{job_id}:{candidate.identity_hash}",
                attributes={
                    "url": candidate.canonical_url,
                    "snippet": hit.snippet,
                    "source": origin["source"],
                    "provider": hit.provider,
                    "evidence_kind": hit.evidence_kind,
                    "qualification": "unverified",
                    "observed_at": origin["observed_at"],
                    "provenance": candidate.provenance,
                },
            )
            ids.append(record["id"])
        JobRepository.event(
            session,
            job_id,
            "discovery:summary",
            "discovery_summary",
            {"source_failures": failures, "result_count": len(ids)},
        )
        return ids

    return StageHandler(
        run,
        persist,
        Decimal(0),
        {},
        lease_seconds=105,
        capacity_kind="http",
        capacity_source="exa_keyless",
        capacity_host="mcp.exa.ai",
        run_with_deadline=run,
        feedback_failure=lambda data: next(
            (entry["failure"] for entry in data if entry.get("failure") is not None), None
        ),
    )


def execute_discovery(database, payload, provider=None):
    identity = TaskIdentity.model_validate(payload)
    handler = discovery_handler(database, identity.actor_id, str(identity.job_id), provider)
    with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
        job = JobRepository.get(session, str(identity.job_id))
        revision = ConversationRepository.get_plan(session, job["plan_id"])
        sources = revision["interpretation"]["sources"]
    handler = replace(handler, dimensions={"search_calls": len(sources)})
    outcome = CheckpointWorker(database, {"discovering": handler}).execute(payload)
    if outcome["status"] not in {"checkpointed", "source_unavailable"}:
        return outcome
    with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
        job = JobRepository.get(session, str(identity.job_id))
        if job["state"] in TERMINAL_STATES:
            return outcome
        events = JobRepository.events_after(session, job["id"])
        failed = outcome["status"] == "source_unavailable" or any(
            row["kind"] == "discovery_summary" and row["details"]["source_failures"]
            for row in events
        )
        finish(
            session,
            job["id"],
            outcome="source_interrupted" if failed else "source_exhausted",
            retained_results=len(result_rows(session, job["id"])),
            expected_version=job["version"],
        )
    return outcome


def dispatch(database, broker_url, actor, workspace):
    return OutboxDispatcher(database, CeleryPublisher(broker_url)).dispatch_batch(
        DispatchScope(actor, workspace), limit=20
    )
