"""Validated environment configuration with explicit production boundaries."""

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SKRILLER_", extra="ignore")
    environment: str = "development"
    database_url: str = Field(
        default="postgresql+psycopg://skriller:local-development@127.0.0.1:54329/skriller",
        repr=False,
    )
    application_database_url: str = Field(
        default="postgresql+psycopg://skriller_app:local-development@127.0.0.1:54329/skriller",
        repr=False,
    )
    broker_url: str = Field(
        default="amqp://skriller:local-development@127.0.0.1:56729//", repr=False
    )
    firebase_project_id: str | None = None
    search_provider: Literal["exa_keyless", "disabled"] = "exa_keyless"
    allow_demo_auth: bool = False
    object_directory: str = ".runtime/objects"
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    @model_validator(mode="after")
    def validate_production(self):
        if self.environment not in {"development", "test", "production"}:
            raise ValueError("Unsupported environment")
        if self.environment == "production":
            if self.allow_demo_auth:
                raise ValueError("Demo authentication is forbidden in production")
            if not self.firebase_project_id:
                raise ValueError("Production requires Firebase project configuration")
            if any(
                "local-development" in value
                for value in (self.database_url, self.application_database_url, self.broker_url)
            ):
                raise ValueError("Production requires explicit database and broker credentials")
        return self
