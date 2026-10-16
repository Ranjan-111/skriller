"""Fence restored/erased automation until a fresh explicit owner opt-in."""

import sqlalchemy as sa

from skriller.db.repositories import require_owner, scope
from skriller.scheduling import schedules
from skriller.webhooks.tables import deliveries, endpoints


def quarantine(session, reason):
    require_owner(session)
    if reason not in {"data_erasure", "restore_requires_opt_in"}:
        raise ValueError("Unsupported automation quarantine reason")
    session.execute(
        sa.update(endpoints)
        .where(endpoints.c.workspace_id == scope(session))
        .values(enabled=False, secret_ciphertext=b"")
    )
    session.execute(
        sa.update(deliveries)
        .where(
            deliveries.c.workspace_id == scope(session),
            deliveries.c.state.in_(("pending", "delivering")),
        )
        .values(state="cancelled", last_code=reason, lease_token=None, lease_expires_at=None)
    )
    session.execute(
        sa.update(schedules)
        .where(schedules.c.workspace_id == scope(session))
        .values(enabled=False, last_reason=reason, lease_token=None, lease_expires_at=None)
    )
