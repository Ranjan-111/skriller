"""One-use Reddit cursors bound to a job, request and loaded credential generation."""

import hashlib
from datetime import timedelta
from uuid import UUID

import sqlalchemy as sa

from skriller.connections.store import ConnectionUnavailable
from skriller.connectors.reddit_request import RedditCursor
from skriller.db.repositories import insert_row, scope
from skriller.db.schema import scoped

continuations = scoped(
    "reddit_search_continuations",
    sa.Column("job_id", sa.Uuid(as_uuid=False), nullable=False),
    sa.Column("actor_id", sa.String(128), nullable=False),
    sa.Column("connection_id", sa.Uuid(as_uuid=False), nullable=False),
    sa.Column("credential_id", sa.Uuid(as_uuid=False), nullable=False),
    sa.Column("plan_revision", sa.Integer, nullable=False),
    sa.Column("request_hash", sa.String(64), nullable=False),
    sa.Column("after", sa.String(16), nullable=False),
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
)


def request_hash(request):
    if request.cursor is not None:
        raise ConnectionUnavailable()
    return hashlib.sha256(request.model_dump_json().encode()).hexdigest()


def issue(session, store, context, material, request, cursor):
    """Only a current completed read may publish its next opaque reference."""
    if not store.runner_current(session, context, material):
        raise ConnectionUnavailable()
    digest = request_hash(request)
    # A repeated source cursor cannot create an unbounded paging loop.
    existing = session.execute(
        sa.select(continuations.c.id).where(
            continuations.c.workspace_id == scope(session),
            continuations.c.job_id == str(context.job_id),
            continuations.c.credential_id == str(material.credential_ref),
            continuations.c.request_hash == digest,
            continuations.c.after == cursor.after,
        )
    ).scalar_one_or_none()
    if existing:
        return None
    now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
    row = insert_row(
        session,
        continuations,
        job_id=str(context.job_id),
        actor_id=context.actor_id,
        connection_id=str(material.connection_ref),
        credential_id=str(material.credential_ref),
        plan_revision=context.plan_revision,
        request_hash=digest,
        after=cursor.after,
        state="ready",
        expires_at=min(context.deadline, now + timedelta(minutes=5)),
    )
    return UUID(row["id"])


def consume(session, store, context, material, request, identifier):
    """Commit consumption before dispatch; crash or uncertain I/O cannot replay it."""
    if not store.runner_current(session, context, material):
        raise ConnectionUnavailable()
    row = (
        session.execute(
            sa.select(continuations)
            .where(
                continuations.c.workspace_id == scope(session),
                continuations.c.id == str(identifier),
                continuations.c.actor_id == context.actor_id,
                continuations.c.job_id == str(context.job_id),
                continuations.c.connection_id == str(context.connection_ref),
                continuations.c.credential_id == str(material.credential_ref),
                continuations.c.plan_revision == context.plan_revision,
                continuations.c.request_hash == request_hash(request),
                continuations.c.state == "ready",
                continuations.c.expires_at > sa.func.clock_timestamp(),
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ConnectionUnavailable()
    session.execute(
        sa.update(continuations)
        .where(
            continuations.c.workspace_id == scope(session),
            continuations.c.id == row["id"],
        )
        .values(state="consumed")
    )
    return RedditCursor(after=row["after"])
