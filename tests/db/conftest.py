"""Real PostgreSQL schema setup and restricted application-role fixtures."""

import pytest
from alembic import command
from alembic.config import Config

from skriller.db import Database, bootstrap
from skriller.settings import Settings


@pytest.fixture(scope="session")
def database():
    settings = Settings()
    bootstrap(settings.database_url, application_password="local-development")
    config = Config("alembic.ini")
    config.attributes["database_url"] = settings.database_url
    command.upgrade(config, "head")
    app_url = getattr(
        settings,
        "application_database_url",
        settings.database_url.replace("://skriller:", "://skriller_app:"),
    )
    db = Database(app_url, pool_size=1)
    yield db
    db.dispose()
