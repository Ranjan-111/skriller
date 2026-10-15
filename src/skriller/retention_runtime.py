"""Hourly durable tenant cleanup; run alongside the research worker."""

import json
import logging
import sys
import time
from pathlib import Path
from uuid import UUID

import sqlalchemy as sa
from agent_reach.utils.process import utf8_subprocess_env
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from skriller.db import Database
from skriller.db.repositories import scope
from skriller.db.schema import metadata
from skriller.retention import cleanup_expired
from skriller.security.runner import bounded_process
from skriller.settings import Settings
from skriller.storage.configuration import configured_storage

schedules = sa.Table(
    "retention_schedules",
    metadata,
    sa.Column(
        "workspace_id", PGUUID(as_uuid=False), sa.ForeignKey("workspaces.id"), primary_key=True
    ),
    sa.Column("actor_id", sa.String(128), nullable=False),
    sa.Column(
        "next_due_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column("lease_token", PGUUID(as_uuid=False)),
    sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
)


class CleanupIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID
    actor_id: str = Field(min_length=1, max_length=128)
    lease_token: UUID


def register(session):
    """Authenticated work registers one schedule; repeated visits do not delay it."""
    query = insert(schedules).values(workspace_id=scope(session), actor_id=session.info["actor_id"])
    session.execute(
        query.on_conflict_do_update(
            index_elements=["workspace_id"], set_={"actor_id": session.info["actor_id"]}
        )
    )


def claim_due(database, limit=10):
    # Fixed service function exposes only bounded opaque task scopes/leases, not
    # evidence or private pages. Each execution still requires tenant membership.
    with Session(database.engine) as session, session.begin():
        database._assert_application_role(session)
        return [
            {
                "workspace_id": str(row["workspace_id"]),
                "actor_id": row["actor_id"],
                "lease_token": str(row["lease_token"]),
            }
            for row in session.execute(
                sa.text("SELECT * FROM claim_due_retention(:limit)"), {"limit": limit}
            ).mappings()
        ]


def execute_cleanup(database, payload, storage):
    identity = CleanupIdentity.model_validate(payload)
    with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
        row = (
            session.execute(
                sa.select(schedules)
                .where(schedules.c.workspace_id == scope(session))
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
        if (
            row is None
            or row["actor_id"] != identity.actor_id
            or row["lease_token"] != str(identity.lease_token)
            or row["lease_expires_at"] is None
            or row["lease_expires_at"] <= now
        ):
            return {"status": "stale_lease", "removed": 0}
        result = cleanup_expired(session, storage)
        if result["status"] == "completed":
            session.execute(
                sa.update(schedules)
                .where(
                    schedules.c.workspace_id == scope(session),
                    schedules.c.lease_token == str(identity.lease_token),
                )
                .values(
                    next_due_at=sa.func.clock_timestamp() + sa.text("interval '1 hour'"),
                    lease_token=None,
                    lease_expires_at=None,
                )
            )
        return result


def run_cleanup_child(payload):
    identity = CleanupIdentity.model_validate(payload)
    result = bounded_process(
        [sys.executable, "-m", "skriller.retention_runtime", "--once", identity.model_dump_json()],
        cwd=Path.cwd(),
        env=utf8_subprocess_env(),
        timeout=45,
        max_output=8192,
    )
    if result.status != "completed" or result.returncode != 0:
        raise RuntimeError("Retention child could not complete within its limits")
    data = json.loads(result.stdout)
    if not isinstance(data, dict) or data.get("status") not in {
        "completed",
        "stale_lease",
        "leased",
    }:
        raise ValueError("Invalid retention child result")
    return data


def tick(database, storage, *, bounded=False):
    completed = 0
    for payload in claim_due(database):
        try:
            result = (
                run_cleanup_child(payload)
                if bounded
                else execute_cleanup(database, payload, storage)
            )
            completed += result["status"] == "completed"
        except Exception:  # noqa: BLE001 - expiry lease permits retry; never log body/key/credentials
            logging.getLogger(__name__).warning(
                "Retention batch failed; its lease will permit retry"
            )
            continue
    return completed


if __name__ == "__main__":
    settings = Settings()
    database = Database(settings.application_database_url)
    storage = configured_storage(settings)
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "--once":
            print(json.dumps(execute_cleanup(database, json.loads(sys.argv[2]), storage)))
            sys.exit(0)
        while True:
            try:
                tick(database, storage, bounded=True)
            except sa.exc.SQLAlchemyError:
                logging.getLogger(__name__).warning(
                    "Retention database unavailable; retrying later"
                )
            time.sleep(60)
    finally:
        try:
            storage.close()
        finally:
            database.dispose()
