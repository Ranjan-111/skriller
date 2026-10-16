"""Authenticated encryption and trusted runner loading of scoped credentials."""

import json
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from agent_reach.utils.text import scrub_url_credentials
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, ConfigDict, SecretStr, model_validator

from skriller.connections.keys import Keyring, KeyUnavailable
from skriller.connections.tables import connection_audit, connections, secrets
from skriller.contracts import ExecutionContext, Source
from skriller.db import ConversationRepository, JobRepository, WorkspaceAccessDenied
from skriller.db.repositories import insert_row, require_owner, scope
from skriller.jobs.control import permit_call

RUNNERS = {
    "proxy_route": ("proxy", {"api_key": "SKR_PROXY_CONFIGURATION"}),
    "linkedin_read": (
        "linkedin",
        {"session_cookie": "LINKEDIN_SESSION_COOKIE", "access_token": "LINKEDIN_ACCESS_TOKEN"},
    ),
    "reddit_read": (
        "reddit",
        {"access_token": "REDDIT_ACCESS_TOKEN", "session_cookie": "REDDIT_SESSION_COOKIE"},
    ),
    "github_read": ("github", {"access_token": "GITHUB_TOKEN"}),
    "youtube_read": ("youtube", {"api_key": "YOUTUBE_API_KEY"}),
    # X reads use the documented OAuth API. Session cookies are not accepted by
    # this runner, which deliberately has no browser/session transport.
    "x_read": ("x", {"access_token": "X_ACCESS_TOKEN"}),
    "instagram_read": ("instagram", {"session_cookie": "INSTAGRAM_SESSION_COOKIE"}),
    "facebook_read": (
        "facebook",
        {"session_cookie": "FACEBOOK_SESSION_COOKIE", "access_token": "FACEBOOK_ACCESS_TOKEN"},
    ),
}


class ConnectionUnavailable(RuntimeError):
    state = "needs_connection"

    def __init__(self, reason="connection_unavailable"):
        self.reason = reason
        super().__init__("Source connection needs configuration or reconnection")


class SecretPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    credentials: dict[str, SecretStr]

    @model_validator(mode="after")
    def bounds(self):
        if not 1 <= len(self.credentials) <= 3 or not set(self.credentials) <= {
            "session_cookie",
            "access_token",
            "refresh_token",
            "api_key",
        }:
            raise ValueError("Unsupported credential fields")
        if any(
            not 1 <= len(value.get_secret_value()) <= 16384 for value in self.credentials.values()
        ):
            raise ValueError("Credential field exceeds supported bounds")
        if (
            len(
                json.dumps(
                    {name: value.get_secret_value() for name, value in self.credentials.items()}
                ).encode()
            )
            > 32768
        ):
            raise ValueError("Credential payload exceeds supported bounds")
        return self


@dataclass(frozen=True)
class ConnectionReference:
    id: UUID
    workspace_id: UUID
    source: str
    auth_kind: str
    scopes: tuple[str, ...]
    state: str
    expires_at: datetime


@dataclass(frozen=True)
class RunnerSecrets:
    connection_ref: UUID
    runner: str
    environment: dict[str, SecretStr] = field(repr=False)
    credential_ref: UUID | None = None

    def injection(self) -> dict[str, str]:
        """Only the fixed runner launch boundary may consume this environment."""
        return {name: value.get_secret_value() for name, value in self.environment.items()}


def redact_output(text: object, material: RunnerSecrets | None = None) -> str:
    """Adapt copied URL redaction, add exact known secrets and credential headers."""
    result = scrub_url_credentials(text)
    if material:
        for value in sorted(
            (item.get_secret_value() for item in material.environment.values()),
            key=len,
            reverse=True,
        ):
            result = result.replace(value, "[REDACTED]")
    result = re.sub(
        r"(?im)\b(?:cookie|set-cookie|authorization)\s*:\s*[^\r\n]+", "[REDACTED HEADER]", result
    )
    result = re.sub(r"(?im)\b(?:cookie|set-cookie)\s*=\s*[^\r\n]+", "[REDACTED COOKIE]", result)
    result = re.sub(
        r"(?i)\b(?:access_token|refresh_token|api_key|authorization)\s*=\s*[^\s,;]+",
        "[REDACTED FIELD]",
        result,
    )
    return result.encode()[:8192].decode("utf-8", errors="ignore")


def _reference(row):
    state = (
        "expired"
        if row["state"] == "active" and row["expires_at"] <= datetime.now(UTC)
        else row["state"]
    )
    return ConnectionReference(
        UUID(row["id"]),
        UUID(row["workspace_id"]),
        row["source"],
        row["auth_kind"],
        tuple(row["scopes"]),
        state,
        row["expires_at"],
    )


def _aad(workspace, connection_id, source, secret_id, version):
    return json.dumps(
        [1, str(workspace), str(connection_id), source, str(secret_id), version],
        separators=(",", ":"),
    ).encode()


def _lock(session, connection_id):
    session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:identity,0))"),
        {"identity": f"connection:{scope(session)}:{connection_id}"},
    )


class ConnectionStore:
    def __init__(self, keyring: Keyring | None):
        self.keyring = keyring

    @classmethod
    def configured(cls, settings):
        try:
            return cls(Keyring.load(settings.source_encryption_key_file))
        except KeyUnavailable:
            return cls(None)

    def create(
        self,
        session,
        source: str,
        auth_kind: Literal["session", "oauth", "api_key"],
        payload: SecretPayload,
        *,
        expires_at: datetime,
        scopes: tuple[str, ...] = ("read",),
    ):
        require_owner(session)
        if self.keyring is None:
            raise ConnectionUnavailable("encryption_key_missing")
        allowed_fields = {
            "session": {"session_cookie"},
            "oauth": {"access_token", "refresh_token"},
            "api_key": {"api_key"},
        }
        if (
            source not in {config[0] for config in RUNNERS.values()}
            or auth_kind not in allowed_fields
        ):
            raise ValueError("Unsupported source connection")
        if (
            not isinstance(payload, SecretPayload)
            or not set(payload.credentials) <= allowed_fields[auth_kind]
        ):
            raise ValueError("Credential fields do not match authentication kind")
        if source == "x" and (auth_kind != "oauth" or set(payload.credentials) != {"access_token"}):
            raise ValueError(
                "X reads require an OAuth access token; session cookies are unsupported"
            )
        if auth_kind == "oauth" and "access_token" not in payload.credentials:
            raise ValueError("OAuth connection needs an access token")
        if (
            not 1 <= len(scopes) <= 2
            or len(set(scopes)) != len(scopes)
            or not set(scopes) <= {"read", "discover"}
        ):
            raise ValueError("Connection supports read-only scopes")
        now = datetime.now(UTC)
        if expires_at.tzinfo is None or not now < expires_at <= now + timedelta(days=30):
            raise ValueError("Credential retention must expire within 30 days")
        if source == "proxy":
            if auth_kind != "api_key" or set(payload.credentials) != {"api_key"}:
                raise ValueError("Proxy connection requires encrypted provider configuration")
            from skriller.connectors.proxies import ProxyConfiguration

            ProxyConfiguration.parse(payload.credentials["api_key"].get_secret_value())
        identifier, secret_id = str(uuid4()), str(uuid4())
        row = insert_row(
            session,
            connections,
            id=identifier,
            source=source,
            auth_kind=auth_kind,
            scopes=list(scopes),
            state="active",
            expires_at=expires_at,
            created_by=session.info["actor_id"],
        )
        nonce = os.urandom(12)
        plaintext = json.dumps(
            {
                "credentials": {
                    name: value.get_secret_value() for name, value in payload.credentials.items()
                }
            }
        ).encode()
        cipher = AESGCM(self.keyring.keys[self.keyring.active]).encrypt(
            nonce,
            plaintext,
            _aad(scope(session), identifier, source, secret_id, self.keyring.active),
        )
        insert_row(
            session,
            secrets,
            id=secret_id,
            connection_id=identifier,
            key_version=self.keyring.active,
            nonce=nonce,
            ciphertext=cipher,
        )
        insert_row(
            session,
            connection_audit,
            connection_id=identifier,
            actor_id=session.info["actor_id"],
            action="created",
        )
        return _reference(row)

    def metadata(self, session, connection_id: UUID):
        row = (
            session.execute(
                sa.select(connections).where(
                    connections.c.workspace_id == scope(session),
                    connections.c.id == str(connection_id),
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ConnectionUnavailable()
        return _reference(row)

    def load_for_runner(self, session, context: ExecutionContext, runner: str) -> RunnerSecrets:
        if runner not in RUNNERS or context.connection_ref is None or self.keyring is None:
            raise ConnectionUnavailable("runner_or_key_unavailable")
        if (
            str(context.workspace_id) != scope(session)
            or context.actor_id != session.info["actor_id"]
        ):
            raise WorkspaceAccessDenied("Connection execution scope mismatch")
        job = JobRepository.get(session, str(context.job_id))
        if (
            job is None
            or job["created_by"] != context.actor_id
            or job["state"] not in {"queued", "running"}
        ):
            raise ConnectionUnavailable("job_not_dispatchable")
        plan = ConversationRepository.get_plan(session, job["plan_id"])
        if (
            plan["revision"] != context.plan_revision
            or datetime.now(UTC) >= context.deadline
            or context.attempt_budget < 1
            or not permit_call(session, str(context.job_id))
        ):
            raise ConnectionUnavailable("execution_expired")
        _lock(session, context.connection_ref)
        reference = self.metadata(session, context.connection_ref)
        source, bindings = RUNNERS[runner]
        source = cast(Source, source)
        from skriller.connectors.switches import is_disabled

        if (
            reference.state != "active"
            or reference.source != source
            or "read" not in reference.scopes
            or (source == "x" and "discover" not in reference.scopes)
            or (runner != "proxy_route" and source not in plan["interpretation"]["sources"])
            or (runner != "proxy_route" and is_disabled(session, source, "read"))
        ):
            raise ConnectionUnavailable("source_scope_unavailable")
        row = (
            session.execute(
                sa.select(secrets).where(
                    secrets.c.workspace_id == scope(session),
                    secrets.c.connection_id == str(reference.id),
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or row["key_version"] not in self.keyring.keys:
            raise ConnectionUnavailable("credential_version_unavailable")
        try:
            plaintext = AESGCM(self.keyring.keys[row["key_version"]]).decrypt(
                row["nonce"],
                row["ciphertext"],
                _aad(scope(session), reference.id, source, row["id"], row["key_version"]),
            )
            payload = SecretPayload.model_validate_json(plaintext)
        except (InvalidTag, ValueError, TypeError):
            raise ConnectionUnavailable("credential_integrity_failed") from None
        environment = {
            bindings[name]: value for name, value in payload.credentials.items() if name in bindings
        }
        if not environment:
            raise ConnectionUnavailable("credential_kind_unavailable")
        insert_row(
            session,
            connection_audit,
            connection_id=str(reference.id),
            actor_id=context.actor_id,
            action="loaded",
            runner=runner,
        )
        return RunnerSecrets(reference.id, runner, environment, UUID(row["id"]))

    def runner_current(self, session, context: ExecutionContext, material: RunnerSecrets) -> bool:
        """Check a loaded generation without decrypting it or repeating load audit rows."""
        from skriller.connectors.switches import is_disabled

        if (
            material.runner not in RUNNERS
            or material.credential_ref is None
            or context.connection_ref != material.connection_ref
            or str(context.workspace_id) != scope(session)
            or context.actor_id != session.info["actor_id"]
            or context.deadline <= datetime.now(UTC)
            or context.attempt_budget < 1
        ):
            return False
        job = JobRepository.get(session, str(context.job_id))
        if (
            job is None
            or job["created_by"] != context.actor_id
            or not permit_call(session, job["id"])
        ):
            return False
        plan = ConversationRepository.get_plan(session, job["plan_id"])
        source, _ = RUNNERS[material.runner]
        source = cast(Source, source)
        if (
            plan is None
            or plan["revision"] != context.plan_revision
            or source != "proxy"
            and source not in plan["interpretation"]["sources"]
            or source != "proxy"
            and is_disabled(session, source, "read")
        ):
            return False
        _lock(session, material.connection_ref)
        try:
            reference = self.metadata(session, material.connection_ref)
        except ConnectionUnavailable:
            return False
        if (
            reference.source != source
            or reference.state != "active"
            or "read" not in reference.scopes
            or (source == "x" and "discover" not in reference.scopes)
        ):
            return False
        return (
            session.execute(
                sa.select(secrets.c.id).where(
                    secrets.c.workspace_id == scope(session),
                    secrets.c.connection_id == str(reference.id),
                    secrets.c.id == str(material.credential_ref),
                )
            ).scalar_one_or_none()
            is not None
        )

    def revoke(self, session, connection_id: UUID):
        require_owner(session)
        _lock(session, connection_id)
        reference = self.metadata(session, connection_id)
        if reference.state == "revoked":
            return reference
        session.execute(
            sa.delete(secrets).where(
                secrets.c.workspace_id == scope(session),
                secrets.c.connection_id == str(connection_id),
            )
        )
        row = (
            session.execute(
                sa.update(connections)
                .where(
                    connections.c.workspace_id == scope(session),
                    connections.c.id == str(connection_id),
                )
                .values(state="revoked", revoked_at=sa.func.now())
                .returning(connections)
            )
            .mappings()
            .one()
        )
        insert_row(
            session,
            connection_audit,
            connection_id=str(connection_id),
            actor_id=session.info["actor_id"],
            action="revoked",
        )
        return _reference(row)

    def purge_expired(self, session):
        require_owner(session)
        identifiers = (
            session.execute(
                sa.select(connections.c.id).where(
                    connections.c.workspace_id == scope(session),
                    connections.c.state == "active",
                    connections.c.expires_at <= sa.func.now(),
                )
            )
            .scalars()
            .all()
        )
        for identifier in identifiers:
            _lock(session, identifier)
            session.execute(
                sa.delete(secrets).where(
                    secrets.c.workspace_id == scope(session), secrets.c.connection_id == identifier
                )
            )
            session.execute(
                sa.update(connections)
                .where(connections.c.workspace_id == scope(session), connections.c.id == identifier)
                .values(state="expired")
            )
            insert_row(
                session,
                connection_audit,
                connection_id=identifier,
                actor_id=session.info["actor_id"],
                action="expired",
            )
        return len(identifiers)
