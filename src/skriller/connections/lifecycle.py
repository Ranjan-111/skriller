"""Local lifecycle only; provider authorization and task rebinding remain explicit."""

from dataclasses import asdict
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa

from skriller.connections.store import ConnectionStore, SecretPayload
from skriller.connections.tables import connections
from skriller.db.repositories import require_owner, scope


def list_metadata(session, store: ConnectionStore) -> list[dict]:
    ids = (
        session.execute(
            sa.select(connections.c.id)
            .where(
                connections.c.workspace_id == scope(session),
            )
            .order_by(connections.c.created_at, connections.c.id)
        )
        .scalars()
        .all()
    )
    return [asdict(store.metadata(session, UUID(identifier))) for identifier in ids]


def reconnect(
    session,
    store: ConnectionStore,
    connection_id: UUID,
    payload: SecretPayload,
    *,
    expires_at: datetime,
    scopes: tuple[str, ...] | None = None,
    auth_kind=None,
):
    """Replace credentials atomically; old opaque references cannot be reused.

    No job, attempt, or checkpoint is changed by connection configuration. A
    future source-specific resume operation must explicitly bind the new ref.
    """
    require_owner(session)
    previous = store.metadata(session, connection_id)
    replacement = store.create(
        session,
        previous.source,
        auth_kind or previous.auth_kind,
        payload,
        expires_at=expires_at,
        scopes=scopes or previous.scopes,
    )
    store.revoke(session, previous.id)
    return replacement
