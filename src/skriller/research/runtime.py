"""Durable local research worker: python -m skriller.research.runtime.

RabbitMQ carries IDs only; PostgreSQL checkpoints survive worker restarts.
"""

import argparse
import sys

import sqlalchemy as sa

from skriller.db import Database, JobRepository
from skriller.db.schema import attempts
from skriller.jobs.budget import locked_job
from skriller.jobs.control import permit_call
from skriller.jobs.worker import CheckpointWorker, TaskIdentity, create_worker_app
from skriller.research.bootstrap import execute_planning
from skriller.research.collection import execute_collection
from skriller.research.followups import execute_followup
from skriller.research.page_extraction import execute_page_extraction
from skriller.research.service import dispatch, execute_discovery
from skriller.settings import Settings

settings = Settings()
database = Database(settings.application_database_url)
app = create_worker_app(database, settings.broker_url, {})
# Replace generic handlers with the source-specific trusted orchestration.
app.tasks.pop("skriller.jobs.execute_job", None)
app.tasks.pop("skriller.jobs.execute_attempt", None)


@app.task(name="skriller.jobs.execute_job", shared=False, lazy=False)
def schedule(payload):
    identity = TaskIdentity.model_validate(payload)
    with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
        from skriller.retention_runtime import register

        register(session)
    outcome = CheckpointWorker(database, {}).schedule(payload)
    dispatch(database, settings.broker_url, identity.actor_id, str(identity.workspace_id))
    return outcome


@app.task(name="skriller.jobs.execute_attempt", bind=True, shared=False, lazy=False)
def execute(self, payload):
    identity = TaskIdentity.model_validate(payload)
    with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
        purpose = locked_job(session, str(identity.job_id))["purpose"]
        stage = session.execute(
            sa.select(attempts.c.stage).where(
                attempts.c.workspace_id == str(identity.workspace_id),
                attempts.c.job_id == str(identity.job_id),
                attempts.c.id == str(identity.attempt_id),
            )
        ).scalar_one()
    reusing = False
    if stage == "discovering" and settings.search_provider == "disabled":
        from skriller.research.refinements import refinement_source

        with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
            reusing = refinement_source(session, str(identity.job_id)) is not None
    if stage == "discovering" and settings.search_provider == "disabled" and not reusing:
        with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
            job = locked_job(session, str(identity.job_id))
            if job["state"] in {"queued", "running"}:
                JobRepository.transition(
                    session, job["id"], "paused", failure_code="search_disabled"
                )
                JobRepository.event(
                    session,
                    job["id"],
                    f"configuration:{identity.attempt_id}:disabled",
                    "discovery_summary",
                    {
                        "source_failures": [{"source": "search", "code": "source_disabled"}],
                        "result_count": 0,
                    },
                )
        return {"status": "source_disabled"}
    if stage == "reporting" and purpose == "owner_summary":
        from skriller.analytics.jobs import execute_summary
        from skriller.analytics.private_jobs import PrivateSummaryStore
        from skriller.analytics.service import AnalyticsStore
        from skriller.connections.keys import Keyring

        outcome = execute_summary(
            database,
            payload,
            PrivateSummaryStore(AnalyticsStore(Keyring.load(settings.source_encryption_key_file))),
        )
    elif stage == "reporting":
        outcome = execute_followup(database, payload)
    elif stage == "planning":
        outcome = execute_planning(database, payload, settings)
    elif stage == "discovering":
        x_reader = None
        reddit_reader = None
        linkedin_reader = None
        instagram_reader = None
        facebook_reader = None
        reddit_renewal = None
        connection_store = None
        if settings.public_linkedin_image:
            from skriller.connections.store import ConnectionStore
            from skriller.connectors.linkedin_executor import ConcreteLinkedInExecutor

            linkedin_reader = ConcreteLinkedInExecutor(settings.public_linkedin_image)
            connection_store = ConnectionStore.configured(settings)
        if settings.public_social_image:
            from skriller.connections.store import ConnectionStore
            from skriller.connectors.social_executor import ConcreteSocialExecutor

            instagram_reader = ConcreteSocialExecutor("instagram", settings.public_social_image)
            facebook_reader = ConcreteSocialExecutor("facebook", settings.public_social_image)
            connection_store = ConnectionStore.configured(settings)
        if settings.public_x_image:
            from skriller.connections.store import ConnectionStore
            from skriller.connectors.x_executor import ConcreteXExecutor

            x_reader = ConcreteXExecutor(settings.public_x_image)
            connection_store = ConnectionStore.configured(settings)
        if settings.public_reddit_image:
            from skriller.connections.store import ConnectionStore
            from skriller.connectors.reddit_executor import ConcreteRedditExecutor

            reddit_reader = ConcreteRedditExecutor(
                settings.public_reddit_image, user_agent=settings.reddit_oauth_user_agent
            )
            connection_store = ConnectionStore.configured(settings)
            from skriller.connections.reddit_oauth import RedditConsentStore
            from skriller.connections.reddit_renewal import RedditAccessRenewal
            from skriller.connectors.reddit_oauth import (
                RedditOAuth,
                RedditOAuthUnavailable,
                configuration,
            )

            try:
                config = configuration(settings)
            except RedditOAuthUnavailable:
                pass  # Imported access references do not imply a refresh grant.
            else:
                reddit_renewal = RedditAccessRenewal(
                    database,
                    RedditConsentStore(connection_store.keyring),
                    config,
                    RedditOAuth(),
                ).prepare
        outcome = execute_discovery(
            database,
            payload,
            collection_proxy_url=settings.public_collection_proxy_url,
            x_reader=x_reader,
            reddit_reader=reddit_reader,
            linkedin_reader=linkedin_reader,
            instagram_reader=instagram_reader,
            facebook_reader=facebook_reader,
            connection_store=connection_store,
            reddit_renewal=reddit_renewal,
        )
    elif stage == "collecting" and settings.public_collection_proxy_url:
        browser = None
        youtube_reader = None
        reddit_reader = linkedin_reader = instagram_reader = facebook_reader = connection_store = (
            None
        )
        if settings.public_linkedin_image:
            from skriller.connections.store import ConnectionStore
            from skriller.connectors.linkedin_executor import ConcreteLinkedInExecutor

            linkedin_reader = ConcreteLinkedInExecutor(settings.public_linkedin_image)
            connection_store = ConnectionStore.configured(settings)
        if settings.public_social_image:
            from skriller.connections.store import ConnectionStore
            from skriller.connectors.social_executor import ConcreteSocialExecutor

            instagram_reader = ConcreteSocialExecutor("instagram", settings.public_social_image)
            facebook_reader = ConcreteSocialExecutor("facebook", settings.public_social_image)
            connection_store = ConnectionStore.configured(settings)
        if settings.public_reddit_image:
            from skriller.connections.store import ConnectionStore
            from skriller.connectors.reddit_executor import ConcreteRedditExecutor

            reddit_reader = ConcreteRedditExecutor(settings.public_reddit_image)
            connection_store = ConnectionStore.configured(settings)
        if settings.public_youtube_image:
            from skriller.connectors.youtube_executor import ConcreteYouTubeExecutor

            youtube_reader = ConcreteYouTubeExecutor(settings.public_youtube_image)
        if settings.enable_dynamic_collection and settings.public_browser_image:
            from skriller.connectors.browser import DynamicBrowserAdapter
            from skriller.connectors.browser_executor import ConcreteBrowserExecutor

            browser = DynamicBrowserAdapter(
                database,
                executor=ConcreteBrowserExecutor(settings.public_browser_image),
                isolation_verified=True,
                stealth=settings.enable_stealth_collection,
            )
        outcome = execute_collection(
            database,
            payload,
            settings.public_collection_proxy_url,
            enable_extraction=settings.enable_page_extraction,
            browser=browser,
            cache_ttl_seconds=settings.public_response_cache_ttl_seconds,
            youtube_reader=youtube_reader,
            reddit_reader=reddit_reader,
            linkedin_reader=linkedin_reader,
            instagram_reader=instagram_reader,
            facebook_reader=facebook_reader,
            connection_store=connection_store,
        )
    elif stage == "extracting" and purpose == "template_repair" and settings.enable_page_extraction:
        from skriller.research.template_repair import execute_template_repair
        from skriller.storage.configuration import configured_storage

        with configured_storage(settings) as storage:
            outcome = execute_template_repair(database, payload, storage=storage)
    elif stage == "extracting" and settings.enable_page_extraction:
        outcome = execute_page_extraction(database, payload, settings=settings)
    else:
        if stage in {"collecting", "extracting"}:
            with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
                job = locked_job(session, str(identity.job_id))
                if job["state"] in {"queued", "running"}:
                    JobRepository.transition(
                        session, job["id"], "paused", failure_code=f"{stage}_disabled"
                    )
        return {"status": "unsupported_operation"}
    if stage in {"planning", "discovering", "collecting"}:
        dispatch(database, settings.broker_url, identity.actor_id, str(identity.workspace_id))
    if outcome["status"] in {"leased", "capacity_exhausted"}:
        identity = TaskIdentity.model_validate(payload)
        with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
            remaining = permit_call(session, str(identity.job_id))
        if remaining > 0:
            raise self.retry(
                exc=RuntimeError("Research is waiting for shared capacity"),
                countdown=min(5, remaining),
                max_retries=30,
            )
    return outcome


def worker_arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pool",
        choices=["solo", "prefork"],
        default="solo" if sys.platform == "darwin" else "prefork",
    )
    arguments = parser.parse_args(argv)
    return [
        "worker",
        f"--pool={arguments.pool}",
        "--concurrency=1" if arguments.pool == "solo" else "--concurrency=2",
        "--loglevel=WARNING",
        "--without-mingle",
        "--without-gossip",
    ]


if __name__ == "__main__":
    app.worker_main(worker_arguments())
