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
from skriller.connectors.switches import is_disabled
from skriller.db import ConversationRepository, JobRepository, ResearchRepository
from skriller.db.repositories import scope
from skriller.db.schema import attempts, entities, messages
from skriller.jobs.control import permit_call
from skriller.jobs.outbox import CeleryPublisher, DispatchScope, OutboxDispatcher
from skriller.jobs.state import TERMINAL_STATES, finish
from skriller.jobs.worker import CheckpointWorker, StageHandler, TaskIdentity
from skriller.research.queries import build_queries

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
    by_id = {
        identifier: row for identifier, row in by_id.items() if not row["attributes"].get("erased")
    }
    from skriller.retention import current_observations

    for identifier, row in list(by_id.items()):
        attributes = dict(row["attributes"])
        if attributes.get("extraction") is not None:
            extracted = dict(attributes["extraction"])
            current, omitted = current_observations(session, identifier, extracted["observations"])
            extracted.update(observations=current, expired_observations=omitted)
            attributes["extraction"] = extracted
        by_id[identifier] = {**row, "attributes": attributes}
    return [
        {
            "id": identifier,
            "title": by_id[identifier]["display_name"],
            **{
                key: value
                for key, value in by_id[identifier]["attributes"].items()
                if not key.startswith("_collection_")
            },
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

        batch = build_queries(plan, prompt)
        if batch.stop_reason:
            # A bounded/clarification stop is not a successful empty search.
            # Keep the reason visible and never invoke the provider.
            return (
                [
                    {
                        "source": source,
                        "page": None,
                        "error": batch.stop_reason,
                        "failure": None,
                        "query_warnings": list(batch.warnings),
                    }
                    for source in plan.sources or ["query"]
                ],
                Decimal(0),
                {"search_calls": 0},
            )

        async def discover():
            data, calls = [], 0
            loop = asyncio.get_running_loop()
            # Leave checkpoint time inside the committed attempt/capacity lease.
            window = timeout_seconds - 1 if timeout_seconds > 1 else timeout_seconds * 0.8
            end = loop.time() + max(0, window)
            stop_reason = None
            for variant in batch.variants:
                source = variant.source
                entry = {"source": source, "page": None, "error": stop_reason, "failure": None}
                entry["query_warnings"] = list(batch.warnings)
                if stop_reason:
                    data.append(entry)
                    continue
                with database.tenant(actor, str(plan.workspace_id)) as session:
                    if is_disabled(session, source, "discover"):
                        entry["error"] = "source_disabled"
                        data.append(entry)
                        continue
                    allowed = permit_call(session, job_id)
                time_left = min(allowed, end - loop.time())
                if time_left <= 0:
                    stop_reason = "deadline_exceeded" if allowed else "cancelled"
                    entry["error"] = stop_reason
                    data.append(entry)
                    continue
                calls += 1
                try:
                    async with asyncio.timeout(time_left):
                        request = asyncio.create_task(
                            provider.search(
                                variant.query,
                                objective=variant.objective,
                                limit=min(plan.limits.result_limit, 10),
                                domains=variant.target_domains,
                            )
                        )
                        try:
                            while not request.done():
                                done, _ = await asyncio.wait((request,), timeout=0.5)
                                if done:
                                    break

                                def check_control():
                                    with database.tenant(actor, str(plan.workspace_id)) as session:
                                        return permit_call(session, job_id)

                                if await asyncio.to_thread(check_control) <= 0:
                                    # Propagate interruption to the worker's uncertain-call
                                    # accounting path, rather than refunding dispatched IO.
                                    raise RuntimeError("Research execution was stopped")
                            entry["page"] = await request
                        finally:
                            if not request.done():
                                request.cancel()
                            await asyncio.gather(request, return_exceptions=True)
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
        from skriller.erasure import privacy_lock

        privacy_lock(session)
        ids = []
        failures = [
            {"source": entry["source"], "code": entry["error"]} for entry in data if entry["error"]
        ]
        pages = [(entry["source"], entry["page"]) for entry in data if entry["page"] is not None]
        for candidate in deduplicate(pages, limit=result_limit):
            from skriller.erasure import suppressed

            if suppressed(session, url=candidate.canonical_url):
                continue
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
            {
                "source_failures": failures,
                "result_count": len(ids),
                "query_warnings": list(
                    dict.fromkeys(
                        warning for entry in data for warning in entry.get("query_warnings", [])
                    )
                ),
            },
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


def execute_discovery(database, payload, provider=None, *, collection_proxy_url=None):
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
        if (
            collection_proxy_url
            and outcome["status"] == "checkpointed"
            and revision["interpretation"]["limits"]["fetch_attempts"] > 0
        ):
            from skriller.research.collection import schedule_collection

            if schedule_collection(session, job, outcome["entity_ids"]):
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
