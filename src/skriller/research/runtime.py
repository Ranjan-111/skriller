"""Durable local research worker: python -m skriller.research.runtime.

RabbitMQ carries IDs only; PostgreSQL checkpoints survive worker restarts.
"""

import argparse
import sys

from skriller.db import Database
from skriller.jobs.control import permit_call
from skriller.jobs.worker import CheckpointWorker, TaskIdentity, create_worker_app
from skriller.research.service import dispatch, execute_discovery
from skriller.settings import Settings

settings = Settings()
database = Database(settings.application_database_url)
app = create_worker_app(database, settings.broker_url, {})
# Replace generic handlers with the source-specific trusted orchestration.
app.tasks.pop("skriller.jobs.execute_job", None)
app.tasks.pop("skriller.jobs.execute_attempt", None)


@app.task(name="skriller.jobs.execute_job")
def schedule(payload):
    identity = TaskIdentity.model_validate(payload)
    outcome = CheckpointWorker(database, {}).schedule(payload)
    dispatch(database, settings.broker_url, identity.actor_id, str(identity.workspace_id))
    return outcome


@app.task(name="skriller.jobs.execute_attempt", bind=True)
def execute(self, payload):
    if settings.search_provider == "disabled":
        raise RuntimeError("Discovery provider is disabled")
    outcome = execute_discovery(database, payload)
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
