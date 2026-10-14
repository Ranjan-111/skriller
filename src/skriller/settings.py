"""Validated environment configuration with explicit production boundaries."""

from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
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
    search_commercial_terms_confirmed: bool = False
    enable_ai_planning: bool = False
    public_collection_proxy_url: str | None = None
    enable_page_extraction: bool = False
    enable_dynamic_collection: bool = False
    public_browser_image: str | None = None
    model_provider: Literal["ollama", "groq"] = "ollama"
    ollama_model: Literal["llama3.2:3b", "deepseek-r1:8b"] = "llama3.2:3b"
    groq_api_key: SecretStr | None = Field(
        default=None, validation_alias="GROQ_API_KEY", repr=False
    )
    groq_free_tier_confirmed: bool = False
    allow_demo_auth: bool = False
    object_directory: str = ".runtime/objects"
    source_encryption_key_file: str | None = Field(default=None, repr=False)
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    @field_validator("public_collection_proxy_url", "public_browser_image", mode="before")
    @classmethod
    def empty_optional_configuration(cls, value):
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_production(self):
        if self.environment not in {"development", "test", "production"}:
            raise ValueError("Unsupported environment")
        if self.enable_page_extraction and (
            not self.public_collection_proxy_url or self.enable_ai_planning
        ):
            raise ValueError("Page extraction requires public collection with planning disabled")
        if self.public_collection_proxy_url:
            from skriller.connectors.fetch import HTTPFetcher

            HTTPFetcher(None, trusted_proxy_url=self.public_collection_proxy_url)
        if self.enable_dynamic_collection:
            if not self.public_collection_proxy_url or not self.public_browser_image:
                raise ValueError(
                    "Dynamic collection requires proxy and reviewed immutable browser image"
                )
            from skriller.connectors.browser_executor import ConcreteBrowserExecutor

            ConcreteBrowserExecutor(self.public_browser_image)
        if self.environment == "production":
            if self.public_collection_proxy_url is not None:
                raise ValueError("Public collection requires the isolated deployment gate")
            if self.allow_demo_auth:
                raise ValueError("Demo authentication is forbidden in production")
            if not self.firebase_project_id:
                raise ValueError("Production requires Firebase project configuration")
            if any(
                "local-development" in value
                for value in (self.database_url, self.application_database_url, self.broker_url)
            ):
                raise ValueError("Production requires explicit database and broker credentials")
            if self.search_provider == "exa_keyless" and not self.search_commercial_terms_confirmed:
                raise ValueError("Production Exa search requires confirmed commercial-use terms")
        return self
