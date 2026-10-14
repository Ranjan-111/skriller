"""Owner-controlled, tenant-scoped operation admission; never deletes results."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from skriller.connectors.registry import Operation
from skriller.contracts import Source
from skriller.db.repositories import require_owner, scope
from skriller.db.schema import scoped

source_switches = scoped(
    "source_switches",
    sa.Column("source", sa.String(32), nullable=False),
    sa.Column("operation", sa.String(16), nullable=False),
    sa.Column("disabled", sa.Boolean, nullable=False),
    sa.Column("updated_by", sa.String(128), nullable=False),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    constraints=(
        sa.UniqueConstraint("workspace_id", "source", "operation"),
        sa.CheckConstraint("operation IN ('discover','read','analytics')"),
        sa.CheckConstraint(
            "source IN ('linkedin','reddit','web','github','rss','youtube','x','instagram','facebook')"
        ),
    ),
)


def disabled_operations(session) -> frozenset[tuple[Source, Operation]]:
    rows = session.execute(
        sa.select(source_switches.c.source, source_switches.c.operation).where(
            source_switches.c.workspace_id == scope(session), source_switches.c.disabled.is_(True)
        )
    ).all()
    return frozenset((row.source, row.operation) for row in rows)


def is_disabled(session, source: Source, operation: Operation) -> bool:
    """Call immediately before starting external IO, including queued work."""
    return (source, operation) in disabled_operations(session)


def set_disabled(session, source: Source, operation: Operation, disabled: bool) -> None:
    require_owner(session)
    query = insert(source_switches).values(
        workspace_id=scope(session),
        source=source,
        operation=operation,
        disabled=disabled,
        updated_by=session.info["actor_id"],
    )
    session.execute(
        query.on_conflict_do_update(
            index_elements=["workspace_id", "source", "operation"],
            set_={
                "disabled": disabled,
                "updated_by": session.info["actor_id"],
                "updated_at": sa.func.now(),
            },
        )
    )
