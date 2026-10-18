"""Validated environment configuration with explicit production boundaries."""

from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="SKRILLER_", extra="ignore", hide_input_in_errors=True
    )
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
    reviewed_page_templates_file: str | None = Field(default=None, repr=False)
    enable_dynamic_collection: bool = False
    enable_stealth_collection: bool = False
    public_response_cache_ttl_seconds: int = Field(default=0, ge=0, le=300)
    public_browser_image: str | None = None
    public_youtube_image: str | None = None
    public_x_image: str | None = None
    public_reddit_image: str | None = None
    public_linkedin_image: str | None = None
    public_social_image: str | None = None
    model_provider: Literal["ollama", "groq"] = "ollama"
    groq_model: Literal["openai/gpt-oss-20b", "openai/gpt-oss-120b"] = "openai/gpt-oss-20b"
    ollama_model: Literal["llama3.2:3b", "deepseek-r1:8b"] = "llama3.2:3b"
    groq_api_key: SecretStr | None = Field(
        default=None, validation_alias="GROQ_API_KEY", repr=False
    )
    groq_free_tier_confirmed: bool = False
    allow_demo_auth: bool = False
    object_directory: str = ".runtime/objects"
    object_backend: Literal["local", "s3"] = "local"
    s3_bucket: str | None = Field(default=None, min_length=3, max_length=63)
    s3_region: str = Field(default="us-east-1", pattern=r"^[a-z0-9-]{1,64}$")
    s3_endpoint_url: str | None = Field(default=None, repr=False)
    s3_access_key_id: SecretStr | None = Field(
        default=None, validation_alias="AWS_ACCESS_KEY_ID", repr=False
    )
    s3_secret_access_key: SecretStr | None = Field(
        default=None, validation_alias="AWS_SECRET_ACCESS_KEY", repr=False
    )
    s3_session_token: SecretStr | None = Field(
        default=None, validation_alias="AWS_SESSION_TOKEN", repr=False
    )
    source_encryption_key_file: str | None = Field(default=None, repr=False)
    salesforce_oauth_client_id: str | None = Field(default=None, repr=False)
    salesforce_oauth_client_secret: SecretStr | None = Field(default=None, repr=False)
    salesforce_oauth_redirect_uri: str | None = None
    salesforce_oauth_sandbox: bool = False
    reddit_oauth_client_id: str | None = Field(default=None, repr=False)
    reddit_oauth_client_secret: SecretStr | None = Field(default=None, repr=False)
    reddit_oauth_redirect_uri: str | None = None
    reddit_oauth_user_agent: str | None = Field(default=None, repr=False)
    x_oauth_client_id: str | None = Field(default=None, repr=False)
    x_oauth_client_secret: SecretStr | None = Field(default=None, repr=False)
    x_oauth_redirect_uri: str | None = None
    youtube_analytics_oauth_client_id: str | None = Field(default=None, repr=False)
    youtube_analytics_oauth_client_secret: SecretStr | None = Field(default=None, repr=False)
    youtube_analytics_oauth_redirect_uri: str | None = None
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    @field_validator(
        "public_collection_proxy_url",
        "public_browser_image",
        "public_youtube_image",
        "public_x_image",
        "public_reddit_image",
        "public_linkedin_image",
        "public_social_image",
        "reviewed_page_templates_file",
        "s3_endpoint_url",
        "s3_bucket",
        "s3_access_key_id",
        "s3_secret_access_key",
        "s3_session_token",
        mode="before",
    )
    @classmethod
    def empty_optional_configuration(cls, value):
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_production(self):
        if self.environment not in {"development", "test", "production"}:
            raise ValueError("Unsupported environment")
        if self.object_backend == "s3" and not self.s3_bucket:
            raise ValueError("S3 storage requires a private bucket")
        if bool(self.s3_access_key_id) != bool(self.s3_secret_access_key) or (
            self.s3_session_token is not None and not self.s3_access_key_id
        ):
            raise ValueError("S3 static credentials require a complete key pair")
        if self.s3_endpoint_url:
            from urllib.parse import urlsplit

            endpoint = urlsplit(self.s3_endpoint_url)
            if (
                endpoint.scheme not in {"http", "https"}
                or not endpoint.hostname
                or endpoint.username is not None
                or endpoint.password is not None
                or endpoint.path not in {"", "/"}
                or endpoint.query
                or endpoint.fragment
                or (
                    endpoint.scheme == "http"
                    and (
                        self.environment == "production"
                        or endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}
                    )
                )
            ):
                raise ValueError("S3 endpoint requires HTTPS or a local development endpoint")
        if self.enable_page_extraction and not self.public_collection_proxy_url:
            raise ValueError("Page extraction requires the guarded public collection proxy")
        if self.public_collection_proxy_url:
            from skriller.connectors.fetch import HTTPFetcher

            HTTPFetcher(None, trusted_proxy_url=self.public_collection_proxy_url)
        if self.enable_stealth_collection and not self.enable_dynamic_collection:
            raise ValueError("Stealth collection requires the reviewed isolated dynamic worker")
        if self.public_youtube_image:
            if not self.public_collection_proxy_url:
                raise ValueError("YouTube collection requires the guarded collection proxy")
            from skriller.connectors.youtube_executor import ConcreteYouTubeExecutor

            ConcreteYouTubeExecutor(self.public_youtube_image)
        if self.public_reddit_image:
            from skriller.connectors.reddit_executor import ConcreteRedditExecutor

            ConcreteRedditExecutor(
                self.public_reddit_image, user_agent=self.reddit_oauth_user_agent
            )
            if self.environment == "production" and not self.reddit_oauth_user_agent:
                raise ValueError("Reddit source execution requires a descriptive app User-Agent")
        if self.public_x_image:
            from skriller.connectors.x_executor import ConcreteXExecutor

            ConcreteXExecutor(self.public_x_image)
        if self.public_linkedin_image:
            from skriller.connectors.linkedin_executor import ConcreteLinkedInExecutor

            ConcreteLinkedInExecutor(self.public_linkedin_image)
        if self.public_social_image:
            from skriller.connectors.social_executor import ConcreteSocialExecutor

            ConcreteSocialExecutor("instagram", self.public_social_image)
            ConcreteSocialExecutor("facebook", self.public_social_image)
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
