"""Bounded on-demand renewal for the initiating Reddit grant owner.

Reuses the committed single-use OAuth exchange. It never impersonates an owner,
renews an ambiguous account selection, or rebinds a prior source cursor.
"""

from datetime import timedelta
from uuid import UUID

import sqlalchemy as sa

from skriller.connections.reddit_oauth import consents
from skriller.connections.tables import connections
from skriller.connections.x_oauth import refresh_consent
from skriller.connectors.reddit_oauth import RedditOAuthUnavailable
from skriller.connectors.switches import is_disabled
from skriller.db import JobRepository
from skriller.db.repositories import scope
from skriller.jobs.control import permit_call


class RedditAccessRenewal:
    def __init__(self, database, store, config, provider):
        self.database = database
        self.store = store
        self.config = config
        self.provider = provider

    def prepare(self, actor, workspace, job_id):
        """Refresh once near access expiry, within the original job deadline.

        A member can use existing shared access but cannot open another owner's
        refresh grant. No grant or multiple grants means no implicit selection.
        The expected connection is compared again under the OAuth row lock.
        """
        with self.database.tenant(actor, workspace) as session:
            if session.info["role"] != "owner":
                return False
            if is_disabled(session, "reddit", "discover") or is_disabled(session, "reddit", "read"):
                return False
            now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
            rows = (
                session.execute(
                    sa.select(consents)
                    .where(
                        consents.c.workspace_id == scope(session),
                        consents.c.created_by == actor,
                        consents.c.state == "active",
                        consents.c.expires_at > now,
                    )
                    .limit(2)
                )
                .mappings()
                .all()
            )
            if len(rows) != 1 or not rows[0]["connection_id"]:
                return False
            row = rows[0]
            reference = self.store.connections.metadata(session, UUID(row["connection_id"]))
            if reference.state == "revoked" or reference.expires_at > now + timedelta(seconds=45):
                return False
            # Do not create a second eligible account beside an independently
            # configured connection, including another owner's private grant.
            other = session.execute(
                sa.select(connections.c.id)
                .where(
                    connections.c.workspace_id == scope(session),
                    connections.c.source == "reddit",
                    connections.c.auth_kind == "oauth",
                    connections.c.state == "active",
                    connections.c.expires_at > now,
                    connections.c.id != str(reference.id),
                )
                .limit(1)
            ).scalar_one_or_none()
            if other is not None:
                return False
            # Leave transport and checkpoint margin inside the original job
            # deadline. Renewal never adds time or retries to the source job.
            if permit_call(session, job_id) < 20:
                return False
            identifier = UUID(row["id"])
        try:
            replacement = refresh_consent(
                self.database,
                self.store,
                self.config,
                self.provider,
                actor,
                workspace,
                identifier,
                expected_connection=reference.id,
            )
        except Exception:  # noqa: BLE001 - token/configuration exceptions stay private
            raise RedditOAuthUnavailable() from None
        with self.database.tenant(actor, workspace) as session:
            JobRepository.event(
                session,
                job_id,
                f"reddit:renewed:{replacement.id}",
                "source_access_renewed",
                {"source": "reddit"},
            )
        return True
