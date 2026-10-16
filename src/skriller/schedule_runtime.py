"""Explicit per-workspace due-plan dispatcher; all execution uses existing workers."""

import argparse
import time
from uuid import UUID

from skriller.db import Database
from skriller.jobs.outbox import CeleryPublisher, DispatchScope, OutboxDispatcher
from skriller.scheduling import claim_due, execute_due
from skriller.settings import Settings


def run_once(database, actor_id, workspace_id, *, search_enabled):
    with database.tenant(actor_id, workspace_id) as session:
        task = claim_due(session)
    if task is None:
        return {"status": "idle", "job_id": None}
    with database.tenant(actor_id, workspace_id) as session:
        return execute_due(session, task, search_enabled=search_enabled)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", type=UUID, required=True)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    database = Database(settings.application_database_url)
    dispatcher = OutboxDispatcher(database, CeleryPublisher(settings.broker_url))
    try:
        while True:
            run_once(
                database,
                args.actor_id,
                str(args.workspace_id),
                search_enabled=settings.search_provider != "disabled",
            )
            dispatcher.dispatch_batch(
                DispatchScope(args.actor_id, str(args.workspace_id)), limit=10
            )
            if args.once:
                return
            time.sleep(10)
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
