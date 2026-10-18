"""Bounded search discovery, using copied engines through existing adapters.

This initial executor treats the prompt as a search objective. It does not claim
semantic qualification, page extraction, contact verification or a full planner.
"""

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import ceil
from uuid import UUID

import sqlalchemy as sa
from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from skriller.connections.store import ConnectionStore
from skriller.connections.tables import connections
from skriller.connectors.candidates import deduplicate
from skriller.connectors.linkedin_executor import ConcreteLinkedInExecutor, LinkedInUnavailable
from skriller.connectors.platform_references import (
    connected_linkedin_reference,
    connected_social_reference,
    indexed_platform_reference,
)
from skriller.connectors.reddit_executor import ConcreteRedditExecutor, RedditUnavailable
from skriller.connectors.search import ExaKeylessSearch, SearchPage, SearchUnavailable
from skriller.connectors.social_executor import ConcreteSocialExecutor, SocialUnavailable
from skriller.connectors.switches import is_disabled
from skriller.connectors.x_executor import ConcreteXExecutor, XUnavailable
from skriller.contracts import ExecutionContext
from skriller.db import ConversationRepository, JobRepository, ResearchRepository
from skriller.db.repositories import scope
from skriller.db.schema import attempts, entities, messages, stage_checkpoints
from skriller.jobs.capacity import CapacityUnavailable, acquire, release
from skriller.jobs.control import permit_call
from skriller.jobs.outbox import CeleryPublisher, DispatchScope, OutboxDispatcher
from skriller.jobs.state import TERMINAL_STATES, finish
from skriller.jobs.worker import CheckpointWorker, StageHandler, TaskIdentity
from skriller.research.queries import QueryVariant, build_queries

SESSION_DISCOVERY_SOURCES = {"linkedin", "instagram", "facebook"}

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
    "Source excerpts and indexed references: matching criteria, identities and contacts are unverified.",
    "Public indexed results do not grant access to private or authenticated platform content.",
    "Indexed search returns at most 10 results per request without pagination; connected reads have separate bounded call and result limits.",
    "Fit uses reviewed evidence only; prompt interpretation and subject identity may still require clarification or review.",
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
        reference = (
            indexed_platform_reference(attributes.get("url", ""))
            if attributes.get("provider") == "exa_keyless"
            else connected_linkedin_reference(attributes.get("url", ""))
            if attributes.get("provider") == "linkedin_mcp"
            else connected_social_reference(attributes.get("url", ""), "instagram")
            if attributes.get("provider") == "opencli_instagram"
            else connected_social_reference(attributes.get("url", ""), "facebook")
            if attributes.get("provider") == "opencli_facebook"
            else None
        )
        if reference is not None:
            attributes["platform_reference"] = reference
        if (
            attributes.get("provider") in {"linkedin_mcp", "opencli_instagram", "opencli_facebook"}
            and attributes.get("collection", {}).get("status") == "read"
        ):
            # The old discovery-only notice says no profile was opened. Successful
            # resource reads have their own view; retain discovery in provenance.
            attributes["platform_reference"] = None
        if attributes.get("extraction") is not None:
            extracted = dict(attributes["extraction"])
            current, omitted = current_observations(session, identifier, extracted["observations"])
            extracted.update(observations=current, expired_observations=omitted)
            attributes["extraction"] = extracted
        if attributes.get("feed") is not None:
            feed = dict(attributes["feed"])
            body_id = attributes.get("_collection_body_evidence_id")
            body = (
                ResearchRepository.get_evidence(session, body_id)
                if isinstance(body_id, str)
                else None
            )
            now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
            if (
                body is None
                or body["object_key"] is None
                or body["expires_at"] is not None
                and body["expires_at"] <= now
            ):
                feed.update(entries=[], evidence_expired=True)
            attributes["feed"] = feed
        if attributes.get("youtube") is not None:
            video = dict(attributes["youtube"])
            body_id = attributes.get("_collection_body_evidence_id")
            body = (
                ResearchRepository.get_evidence(session, body_id)
                if isinstance(body_id, str)
                else None
            )
            now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
            unavailable = (
                body is None
                or body["object_key"] is None
                or body["expires_at"] is not None
                and body["expires_at"] <= now
            )
            current = {
                str(item["claim_id"])
                for item in (attributes.get("extraction") or {}).get("observations", [])
            }
            kept = (
                [segment for segment in video["segments"] if str(segment["claim_id"]) in current]
                if not unavailable
                else []
            )
            omitted = len(video["segments"]) - len(kept)
            video.update(
                segments=kept,
                omitted_segments=video["omitted_segments"] + omitted,
                evidence_expired=unavailable or bool(omitted),
            )
            if unavailable:
                video["metadata"] = None
            attributes["youtube"] = video
        if (
            attributes.get("reddit_thread") is not None
            or attributes.get("linkedin_read") is not None
            or attributes.get("social_read") is not None
        ):
            body_id = attributes.get("_collection_body_evidence_id")
            body = (
                ResearchRepository.get_evidence(session, body_id)
                if isinstance(body_id, str)
                else None
            )
            now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
            if (
                body is None
                or body["object_key"] is None
                or body["expires_at"] is not None
                and body["expires_at"] <= now
            ):
                if attributes.get("reddit_thread") is not None:
                    attributes["reddit_thread"] = None
                if attributes.get("linkedin_read") is not None:
                    attributes["linkedin_read"] = None
                if attributes.get("social_read") is not None:
                    attributes["social_read"] = None
        native = attributes.get("_source_native_id") or {}
        if attributes.get("provider") == "exa_keyless" and native.get("namespace") in {
            "reddit_post",
            "reddit_comment",
            "linkedin_activity",
            "linkedin_ugc_post",
        }:
            attributes["discussion"] = {
                "resource_kind": "comment" if native["namespace"] == "reddit_comment" else "post",
                "evidence_kind": "indexed_reference",
                "author_handle": None,
                "author_identity": "unknown",
            }
        by_id[identifier] = {**row, "attributes": attributes}
    result = [
        {
            "id": identifier,
            "title": by_id[identifier]["display_name"],
            **{
                key: value
                for key, value in by_id[identifier]["attributes"].items()
                if not key.startswith("_")
            },
        }
        for identifier in ids
        if identifier in by_id
    ]
    qualified_ids = (
        session.execute(
            sa.select(stage_checkpoints.c.result_refs).where(
                stage_checkpoints.c.workspace_id == scope(session),
                stage_checkpoints.c.job_id == job_id,
                stage_checkpoints.c.stage == "qualifying",
            )
        )
        .scalars()
        .all()
    )
    if qualified_ids:
        from skriller.jobs.control import plan_for_job
        from skriller.qualification.criteria import Fit, rank
        from skriller.qualification.service import qualify_entity

        job = JobRepository.get(session, job_id)
        plan = plan_for_job(session, job)
        completed = {identifier for batch in qualified_ids for identifier in batch["entity_ids"]}
        fits = {
            row["id"]: qualify_entity(session, plan, row["id"])
            for row in result
            if row["id"] in completed
        }
        for row in result:
            if row["id"] in fits:
                row["fit"] = TypeAdapter(Fit).dump_python(fits[row["id"]], mode="json")
        order = {
            identifier: index for index, (identifier, _) in enumerate(rank(tuple(fits.items())))
        }
        result.sort(key=lambda row: (order.get(row["id"], len(order)), row["id"]))
    return result


def workspace_id_for_job(database, actor, job_id):
    return locate(database, actor, JobRepository, job_id)[0]


def discovery_handler(
    database,
    actor,
    job_id,
    provider=None,
    *,
    x_reader: ConcreteXExecutor | None = None,
    reddit_reader: ConcreteRedditExecutor | None = None,
    linkedin_reader: ConcreteLinkedInExecutor | None = None,
    instagram_reader: ConcreteSocialExecutor | None = None,
    facebook_reader: ConcreteSocialExecutor | None = None,
    connection_store: ConnectionStore | None = None,
    reddit_renewal: Callable[[str, str, str], bool] | None = None,
):
    provider = provider or ExaKeylessSearch()
    with database.tenant(actor, workspace_id_for_job(database, actor, job_id)) as session:
        job = JobRepository.get(session, job_id)
        result_limit = ConversationRepository.get_plan(session, job["plan_id"])["interpretation"][
            "limits"
        ]["result_limit"]

    # All source input is loaded with the task's authenticated tenant scope.
    def run(plan, timeout_seconds=110):
        with database.tenant(actor, str(plan.workspace_id)) as session:
            from skriller.scheduling import pinned_prompt

            prompt = pinned_prompt(session, JobRepository.get(session, job_id), plan)
            if prompt is None:
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
            data: list[dict] = []
            calls = 0
            renewal_checked = False
            renewal_failed = False
            session_failed: set[str] = set()
            loop = asyncio.get_running_loop()
            # Leave checkpoint time inside the committed attempt/capacity lease.
            window = timeout_seconds - 1 if timeout_seconds > 1 else timeout_seconds * 0.8
            end = loop.time() + max(0, window)
            stop_reason = None
            pending: list[tuple[QueryVariant, UUID | None, UUID | None]] = [
                (variant, None, None) for variant in batch.variants
            ]
            while pending:
                variant, continuation_ref, bound_connection = pending.pop(0)
                source = variant.source
                entry: dict = {
                    "source": source,
                    "page": None,
                    "error": stop_reason,
                    "failure": None,
                }
                entry["query_warnings"] = list(batch.warnings)
                if source in session_failed:
                    entry["error"] = "source_unavailable"
                    data.append(entry)
                    continue
                if source == "reddit" and renewal_failed:
                    entry["error"] = "needs_connection"
                    data.append(entry)
                    continue
                if calls >= plan.limits.search_calls:
                    stop_reason = stop_reason or "search_budget_exhausted"
                    entry["error"] = stop_reason
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
                        connected_reader = {
                            "x": x_reader,
                            "reddit": reddit_reader,
                            "linkedin": linkedin_reader,
                            "instagram": instagram_reader,
                            "facebook": facebook_reader,
                        }.get(source)
                        if connected_reader is not None and connection_store is not None:
                            if source == "reddit" and reddit_renewal and not renewal_checked:
                                renewal_checked = True
                                renewal = asyncio.create_task(
                                    asyncio.to_thread(
                                        reddit_renewal, actor, str(plan.workspace_id), job_id
                                    )
                                )
                                try:
                                    await asyncio.shield(renewal)
                                except asyncio.CancelledError:
                                    with contextlib.suppress(Exception):
                                        await asyncio.shield(renewal)
                                    raise
                                except Exception:  # noqa: BLE001 - no private renewal errors
                                    renewal_failed = True
                                    entry["error"] = "needs_connection"
                                    data.append(entry)
                                    continue
                                finally:
                                    await asyncio.gather(renewal, return_exceptions=True)
                                # Token I/O used the same wall-clock window.
                                time_left = min(time_left, end - loop.time())
                                if time_left <= 0:
                                    entry["error"] = stop_reason = "deadline_exceeded"
                                    data.append(entry)
                                    continue
                            with database.tenant(actor, str(plan.workspace_id)) as session:
                                connection_rows = (
                                    session.execute(
                                        sa.select(connections.c.id, connections.c.scopes)
                                        .where(
                                            connections.c.workspace_id == scope(session),
                                            connections.c.source == source,
                                            connections.c.auth_kind
                                            == (
                                                "session"
                                                if source in SESSION_DISCOVERY_SOURCES
                                                else "oauth"
                                            ),
                                            connections.c.state == "active",
                                            connections.c.expires_at > sa.func.clock_timestamp(),
                                            *(
                                                [connections.c.created_by == actor]
                                                if source in SESSION_DISCOVERY_SOURCES
                                                else []
                                            ),
                                        )
                                        .order_by(connections.c.created_at.desc())
                                        .limit(20)
                                    )
                                    .mappings()
                                    .all()
                                )
                            account_rows = [
                                row["id"]
                                for row in connection_rows
                                if {"read", "discover"} <= set(row["scopes"])
                            ][:2]
                            if continuation_ref is not None and account_rows != [
                                str(bound_connection)
                            ]:
                                entry["error"] = "needs_connection"
                                data.append(entry)
                                continue
                            if len(account_rows) > 1:
                                entry["error"] = "ambiguous_connection"
                                data.append(entry)
                                continue
                            if account_rows:
                                native_query = variant.query.removeprefix(source + " ")
                                if len(native_query) > (
                                    200 if source in {"instagram", "facebook"} else 500
                                ):
                                    entry["error"] = "query_bound_exceeded"
                                    data.append(entry)
                                    continue
                                connection_ref = UUID(str(account_rows[0]))
                                context = ExecutionContext(
                                    workspace_id=plan.workspace_id,
                                    job_id=UUID(job_id),
                                    actor_id=actor,
                                    plan_revision=plan.revision,
                                    deadline=datetime.now(UTC)
                                    + timedelta(seconds=min(time_left, timeout_seconds)),
                                    connection_ref=connection_ref,
                                    attempt_budget=max(1, plan.limits.search_calls),
                                )
                                lease = None
                                started = asyncio.get_running_loop().time()
                                retry_headers = None
                                try:
                                    # A following page observes the persisted cadence from
                                    # the previous page. Wait only for a short bounded
                                    # capacity window; this never retries a source request.
                                    capacity_end = min(end, loop.time() + 5)
                                    while lease is None:
                                        try:
                                            with database.tenant(
                                                actor, str(plan.workspace_id)
                                            ) as session:
                                                remaining = permit_call(session, job_id)
                                                if remaining <= 0:
                                                    raise CapacityUnavailable()
                                                lease = acquire(
                                                    session,
                                                    job_id,
                                                    kind="browser"
                                                    if source in SESSION_DISCOVERY_SOURCES
                                                    else "http",
                                                    source=source,
                                                    host="api.x.com"
                                                    if source == "x"
                                                    else "www." + source + ".com"
                                                    if source in SESSION_DISCOVERY_SOURCES
                                                    else "oauth.reddit.com",
                                                    ttl_seconds=min(
                                                        60, max(1, ceil(min(remaining, time_left)))
                                                    ),
                                                )
                                        except CapacityUnavailable:
                                            if (
                                                continuation_ref is None
                                                or loop.time() + 0.25 >= capacity_end
                                            ):
                                                raise
                                            await asyncio.sleep(0.25)
                                    search_operation: Callable[..., SearchPage] = (
                                        connected_reader.search_page
                                    )
                                    request = asyncio.create_task(
                                        asyncio.to_thread(
                                            search_operation,
                                            native_query,
                                            limit=min(plan.limits.result_limit, 10),
                                            database=database,
                                            store=connection_store,
                                            context=context,
                                            **(
                                                {"continuation_ref": continuation_ref}
                                                if source == "reddit"
                                                else {}
                                            ),
                                        )
                                    )
                                    try:
                                        entry["page"] = await asyncio.shield(request)
                                    except asyncio.CancelledError:
                                        # Keep the capacity lease until the bounded
                                        # container call has stopped and cleaned up.
                                        with contextlib.suppress(Exception):
                                            await asyncio.shield(request)
                                        raise
                                    finally:
                                        if not request.done():
                                            request.cancel()
                                        await asyncio.gather(request, return_exceptions=True)
                                    entry["provider"] = {
                                        "x": "x_api_v2",
                                        "reddit": "reddit_oauth",
                                        "linkedin": "linkedin_mcp",
                                        "instagram": "opencli_instagram",
                                        "facebook": "opencli_facebook",
                                    }[source]
                                    page = entry["page"]
                                    retained = sum(
                                        len(item["page"].hits)
                                        for item in data
                                        if item["page"] is not None
                                    )
                                    if (
                                        source == "reddit"
                                        and page.continuation_ref is not None
                                        and calls < plan.limits.search_calls
                                        and retained + len(page.hits) < result_limit
                                    ):
                                        pending.append(
                                            (variant, page.continuation_ref, connection_ref)
                                        )
                                except CapacityUnavailable:
                                    entry["error"] = "capacity_exhausted"
                                except (
                                    XUnavailable,
                                    RedditUnavailable,
                                    LinkedInUnavailable,
                                    SocialUnavailable,
                                ) as exc:
                                    entry["error"] = exc.code
                                    if source in SESSION_DISCOVERY_SOURCES:
                                        session_failed.add(source)
                                    if exc.code == "rate_limited":
                                        stop_reason = "rate_limited"
                                        if exc.retry_after_seconds is not None:
                                            retry_headers = {
                                                "Retry-After": str(exc.retry_after_seconds)
                                            }
                                except (ValueError, TypeError):
                                    entry["error"] = "source_unavailable"
                                    if source in SESSION_DISCOVERY_SOURCES:
                                        session_failed.add(source)
                                finally:
                                    if lease is not None:
                                        elapsed = asyncio.get_running_loop().time() - started
                                        with (
                                            contextlib.suppress(Exception),
                                            database.tenant(
                                                actor, str(plan.workspace_id)
                                            ) as session,
                                        ):
                                            release(
                                                session,
                                                lease,
                                                latency=elapsed,
                                                ok=entry["page"] is not None,
                                                headers=retry_headers,
                                            )
                                data.append(entry)
                                continue
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

            if suppressed(session, url=candidate.canonical_url, native_id=candidate.native_id):
                continue
            hit = candidate.hit
            origin = candidate.provenance[0]
            # Bind later native thread reads to the generation used for discovery.
            # Missing/ambiguous older checkpoints require a new run, never rebinding.
            read_bindings = (
                {
                    (str(page.read_connection_ref), str(page.read_credential_ref))
                    for source, page in pages
                    if source == origin["source"]
                    and page.query == origin["query"]
                    and page.read_connection_ref is not None
                    and page.read_credential_ref is not None
                    and any(item.url == origin["original_url"] for item in page.hits)
                }
                if hit.provider
                in {"reddit_oauth", "linkedin_mcp", "opencli_instagram", "opencli_facebook"}
                else set()
            )
            read_binding = next(iter(read_bindings)) if len(read_bindings) == 1 else None
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
                    **(
                        {
                            "_read_connection_ref": read_binding[0],
                            "_read_credential_ref": read_binding[1],
                        }
                        if read_binding
                        else {}
                    ),
                    **({"_source_native_id": candidate.native_id} if candidate.native_id else {}),
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


def execute_discovery(
    database,
    payload,
    provider=None,
    *,
    collection_proxy_url=None,
    x_reader: ConcreteXExecutor | None = None,
    reddit_reader: ConcreteRedditExecutor | None = None,
    linkedin_reader: ConcreteLinkedInExecutor | None = None,
    instagram_reader: ConcreteSocialExecutor | None = None,
    facebook_reader: ConcreteSocialExecutor | None = None,
    connection_store: ConnectionStore | None = None,
    reddit_renewal: Callable[[str, str, str], bool] | None = None,
):
    identity = TaskIdentity.model_validate(payload)
    from skriller.research.refinements import refinement_source, reuse_handler

    with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
        job = JobRepository.get(session, str(identity.job_id))
        revision = ConversationRepository.get_plan(session, job["plan_id"])
        sources = revision["interpretation"]["sources"]
        reusing = refinement_source(session, job["id"]) is not None
    if reusing:
        handler = reuse_handler(
            database, identity.actor_id, str(identity.workspace_id), str(identity.job_id)
        )
    else:
        handler = discovery_handler(
            database,
            identity.actor_id,
            str(identity.job_id),
            provider,
            x_reader=x_reader,
            reddit_reader=reddit_reader,
            linkedin_reader=linkedin_reader,
            instagram_reader=instagram_reader,
            facebook_reader=facebook_reader,
            connection_store=connection_store,
            reddit_renewal=reddit_renewal,
        )
        maximum_calls = (
            revision["interpretation"]["limits"]["search_calls"]
            if (reddit_reader is not None and "reddit" in sources)
            or (linkedin_reader is not None and "linkedin" in sources)
            or (instagram_reader is not None and "instagram" in sources)
            or (facebook_reader is not None and "facebook" in sources)
            else len(sources)
        )
        handler = replace(handler, dimensions={"search_calls": maximum_calls})
    outcome = CheckpointWorker(database, {"discovering": handler}).execute(payload)
    if outcome["status"] not in {"checkpointed", "source_unavailable"}:
        return outcome
    with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
        job = JobRepository.get(session, str(identity.job_id))
        if job["state"] in TERMINAL_STATES:
            return outcome
        if (
            collection_proxy_url
            and not reusing
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
        from skriller.research.qualification import checkpoint_qualification

        retained = result_rows(session, job["id"])
        job = checkpoint_qualification(session, job, retained)
        if job is None:
            return outcome
        finish(
            session,
            job["id"],
            outcome="source_interrupted" if failed else "source_exhausted",
            retained_results=len(retained),
            expected_version=job["version"],
        )
    return outcome


def dispatch(database, broker_url, actor, workspace):
    return OutboxDispatcher(database, CeleryPublisher(broker_url)).dispatch_batch(
        DispatchScope(actor, workspace), limit=20
    )
