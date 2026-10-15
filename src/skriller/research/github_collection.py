"""One bounded public GitHub read per durable collecting attempt."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import monotonic
from urllib.parse import urlsplit

import sqlalchemy as sa

from skriller.connectors.fetch import FetchUnavailable, HTTPFetcher
from skriller.connectors.github import (
    GitHubPublicReader,
    GitHubUnavailable,
    PublicProfile,
    _profile_path,
    _public_html_url,
    _repo_path,
    public_github_binding,
)
from skriller.connectors.switches import is_disabled
from skriller.contracts import ExecutionContext, Failure
from skriller.db import JobRepository, ResearchRepository
from skriller.db.repositories import scope
from skriller.db.schema import entities
from skriller.erasure import privacy_lock, suppressed
from skriller.jobs.control import permit_call
from skriller.jobs.worker import StageHandler


def github_collection_handler(
    database, identity, attributes, entity_id, proxy_url, storage, reader=None
):
    def permitted():
        with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
            return permit_call(session, str(identity.job_id)) > 0 and not is_disabled(
                session, "github", "read"
            )

    def run(plan, timeout_seconds):
        data, failure, calls, duration = None, None, 0, 0.0
        url = attributes["url"]
        parts = [part for part in urlsplit(url).path.split("/") if part]
        if "github" not in plan.sources or attributes["source"] != "github":
            failure = Failure(code="unsupported_operation", message="GitHub read was not selected")
        else:
            try:
                if len(parts) == 1:
                    _profile_path(parts[0])
                    _public_html_url(url, f"/{parts[0]}")
                else:
                    _repo_path(url)
                if not permitted():
                    return (
                        (None, Failure(code="cancelled", message="GitHub read was stopped"), 0.0),
                        Decimal(0),
                        {"fetch_attempts": 0},
                    )
                bounded = min(8.0, max(0, timeout_seconds - 0.2))
                if bounded <= 0:
                    raise TimeoutError()
                context = ExecutionContext(
                    workspace_id=identity.workspace_id,
                    job_id=identity.job_id,
                    actor_id=identity.actor_id,
                    plan_revision=plan.revision,
                    deadline=datetime.now(UTC) + timedelta(seconds=bounded),
                    attempt_budget=1,
                    attempt_id=identity.attempt_id,
                )

                async def read():
                    if reader is not None:  # Controlled fixture injection only.
                        return await public_github_binding(reader).execute(context, url)
                    fetcher = HTTPFetcher(database, trusted_proxy_url=proxy_url)
                    async with fetcher.proxy_for(context, "github") as endpoint:
                        adapter = GitHubPublicReader(
                            trusted_proxy_url=endpoint, timeout_seconds=bounded
                        )
                        return await public_github_binding(adapter).execute(context, url)

                async def invoke():
                    task = asyncio.create_task(read())
                    try:
                        async with asyncio.timeout(bounded):
                            while not task.done():
                                await asyncio.wait((task,), timeout=0.1)
                                if not await asyncio.to_thread(permitted):
                                    raise asyncio.CancelledError()
                            return await task
                    finally:
                        if not task.done():
                            task.cancel()
                        await asyncio.gather(task, return_exceptions=True)

                started = monotonic()
                calls = 1
                try:
                    data = asyncio.run(invoke())
                finally:
                    duration = monotonic() - started
            except FetchUnavailable as error:
                failure = error.failure
            except GitHubUnavailable as error:
                failure = Failure(
                    code=error.code,
                    message="Public GitHub metadata is unavailable",
                    retry_after_seconds=error.retry_after_seconds,
                )
            except ValueError:
                failure = Failure(
                    code="unsupported_operation",
                    message="Only public GitHub profile/repository URLs are supported",
                )
            except (TimeoutError, asyncio.CancelledError):
                failure = Failure(
                    code="source_unavailable",
                    message="GitHub read stopped within its execution bound",
                )
        return (data, failure, duration), Decimal(0), {"fetch_attempts": calls}

    def persist(session, result):
        data, failure, duration = result
        privacy_lock(session)
        entity = (
            session.execute(
                sa.select(entities)
                .where(entities.c.workspace_id == scope(session), entities.c.id == entity_id)
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if (
            entity is None
            or entity["attributes"].get("erased")
            or suppressed(session, entity_id=entity_id, url=attributes["url"])
        ):
            return []
        updated = dict(entity["attributes"])
        native_id = (
            {
                "namespace": "github_profile"
                if isinstance(data.record, PublicProfile)
                else "github_repository",
                "id": str(data.record.id),
            }
            if data is not None
            else None
        )
        if native_id is not None and suppressed(session, native_id=native_id):
            session.execute(
                sa.update(entities)
                .where(entities.c.workspace_id == scope(session), entities.c.id == entity_id)
                .values(
                    attributes={"erased": True}, display_name=None, canonical_key=None, kind="other"
                )
            )
            JobRepository.event(
                session,
                str(identity.job_id),
                f"collection:{identity.attempt_id}",
                "collection_summary",
                {
                    "entity_id": entity_id,
                    "source": "github",
                    "status": "unavailable",
                    "failure_code": "suppressed_identity",
                },
            )
            return []
        summary = {
            "status": "unavailable",
            "failure_code": failure.code if failure else None,
            "network_seconds": None,
        }
        if data is not None:
            record = data.record.model_dump(mode="json")
            # Public API owner data is explicit, bounded metadata; exclude arbitrary
            # nested fields from the retained/exported adapter record.
            if "owner" in record:
                record["owner"] = {
                    key: record["owner"][key] for key in ("login", "type") if key in record["owner"]
                }
            payload = data.model_dump(mode="json")
            payload["record"] = record
            content = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            saved = storage.store(
                session,
                content,
                source_url=data.source_url,
                source_platform="github",
                collected_at=data.observed_at,
                excerpt=content.decode(),
            )
            updated["_collection_body_evidence_id"] = saved["id"]
            updated["_source_native_id"] = native_id
            updated["_source_resource_type"] = (
                "github_profile" if isinstance(data.record, PublicProfile) else "github_repository"
            )
            # These describe the exact API resource, never an inferred company,
            # employment relationship, email, or cross-platform identity.
            fields = (
                {
                    "github_profile_id": "id",
                    "github_followers": "followers",
                    "github_public_repos": "public_repos",
                }
                if isinstance(data.record, PublicProfile)
                else {
                    "github_repository_id": "id",
                    "github_stars": "stargazers_count",
                    "github_forks": "forks_count",
                }
            )
            observations = []
            for field, key in fields.items():
                value = record[key]
                claim = ResearchRepository.claim(
                    session,
                    entity_id,
                    field,
                    value,
                    mode="observed",
                    status="accepted",
                    evidence_ids=[saved["id"]],
                )
                observations.append(
                    {
                        "claim_id": claim["id"],
                        "field": field,
                        "value": value,
                        "quote": json.dumps({key: value}, separators=(",", ":"))[1:-1],
                        "status": claim["status"],
                    }
                )
            updated["extraction"] = {
                "status": "observed",
                "failure_code": None,
                "observations": observations,
                "rejected_claims": 0,
                "coverage_complete": True,
                "omitted_chunks": 0,
            }
            summary.update(
                status="read",
                observed_at=data.observed_at.isoformat(),
                final_url=data.source_url,
                network_seconds=data.network_seconds,
                parser_seconds=data.parser_seconds,
                browser_seconds=None,
                content_hash=saved["content_hash"],
                coverage_complete=True,
                prepared_chunks=0,
            )
        updated["collection"] = summary
        session.execute(
            sa.update(entities)
            .where(entities.c.workspace_id == scope(session), entities.c.id == entity_id)
            .values(attributes=updated)
        )
        JobRepository.event(
            session,
            str(identity.job_id),
            f"collection:{identity.attempt_id}",
            "collection_summary",
            {
                "entity_id": entity_id,
                "source": "github",
                "status": summary["status"],
                "failure_code": summary["failure_code"],
                "provider_io_seconds": duration,
                "network_seconds": data.network_seconds if data is not None else None,
                "parser_seconds": data.parser_seconds if data is not None else None,
                "browser_seconds": None,
            },
        )
        return [entity_id]

    return StageHandler(
        run,
        persist,
        Decimal(0),
        {"fetch_attempts": 1},
        lease_seconds=15,
        run_with_deadline=run,
        capacity_kind="http",
        capacity_source="github",
        capacity_host="api.github.com",
        minimum_interval=0.5,
        feedback_failure=lambda data: data[1],
    )
