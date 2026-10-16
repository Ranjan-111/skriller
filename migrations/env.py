"""Migrations use explicitly configured owner credentials, never tenant sessions."""

import sqlalchemy as sa
from alembic import context

import skriller.analytics.tables
import skriller.billing.access
import skriller.billing.catalog
import skriller.billing.inbox
import skriller.billing.provisioning
import skriller.billing.reconcile
import skriller.connections.tables
import skriller.connectors.switches
import skriller.crm.consents
import skriller.crm.queue
import skriller.crm.store
import skriller.lists
import skriller.qualification.contacts
import skriller.qualification.identity
import skriller.scheduling
import skriller.webhooks.tables  # noqa: F401 - register schema
from skriller.db.schema import metadata
from skriller.settings import Settings

config = context.config
url = config.attributes.get("database_url") or Settings().database_url


def offline():
    context.configure(
        url=url, target_metadata=metadata, literal_binds=True, dialect_opts={"paramstyle": "named"}
    )
    with context.begin_transaction():
        context.run_migrations()


def online():
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    offline()
else:
    online()
