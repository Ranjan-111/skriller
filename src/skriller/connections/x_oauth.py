"""X consent lifecycle adapted from crm.consents; refresh never enters a read worker."""

import hashlib
import hmac
import json
import os
import secrets
from collections.abc import Callable
from datetime import UTC, timedelta
from typing import ClassVar
from uuid import UUID, uuid4

import sqlalchemy as sa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from skriller.connections.store import ConnectionStore, SecretPayload
from skriller.connectors.x_oauth import XOAuthUnavailable, authorization_url, tokens
from skriller.db.repositories import insert_row, require_owner, scope
from skriller.db.schema import scoped
from skriller.erasure import privacy_lock

consents = scoped(
    "x_oauth_consents",
    sa.Column("created_by", sa.String(128), nullable=False),
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("state_hash", sa.String(64)),
    sa.Column("configuration_hash", sa.String(64), nullable=False),
    sa.Column("connection_id", sa.Uuid(as_uuid=False)),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("key_version", sa.String(64), nullable=False),
    sa.Column("nonce", sa.LargeBinary, nullable=False),
    sa.Column("ciphertext", sa.LargeBinary, nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
)


def now(session):
    return session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()


class XConsentStore:
    # Source-specific adapters reuse these encryption, ownership and replay fences.
    table = consents
    source = "x"
    unavailable: type[RuntimeError] = XOAuthUnavailable
    token_values = staticmethod(tokens)
    authorize: ClassVar[Callable[..., str]] = staticmethod(authorization_url)

    def __init__(self, keyring):
        self.connections = ConnectionStore(keyring)
        self.ring = keyring

    @classmethod
    def _aad(cls, row):
        return json.dumps(
            [
                f"skriller-{cls.source}-oauth-v1",
                row["workspace_id"],
                row["id"],
                row["created_by"],
                row["configuration_hash"],
                row.get("connection_id"),
                row["version"],
                row["key_version"],
                row["expires_at"].astimezone(UTC).isoformat(),
            ],
            separators=(",", ":"),
        ).encode()

    def seal(self, row, value):
        nonce = os.urandom(12)
        return {
            "nonce": nonce,
            "ciphertext": AESGCM(self.ring.keys[row["key_version"]]).encrypt(
                nonce, json.dumps(value).encode(), self._aad(row)
            ),
        }

    def open(self, row):
        try:
            return json.loads(
                AESGCM(self.ring.keys[row["key_version"]]).decrypt(
                    row["nonce"], row["ciphertext"], self._aad(row)
                )
            )
        except Exception:  # noqa: BLE001
            raise self.unavailable() from None

    def get(self, session, identifier, *, lock=False):
        require_owner(session)
        query = sa.select(self.table).where(
            self.table.c.workspace_id == scope(session),
            self.table.c.id == str(UUID(str(identifier))),
            self.table.c.created_by == session.info["actor_id"],
        )
        if lock:
            query = query.with_for_update()
        row = session.execute(query).mappings().one_or_none()
        if row is None:
            raise self.unavailable()
        return dict(row)

    def start(self, session, config, *, opt_in):
        require_owner(session)
        if opt_in is not True:
            raise ValueError(f"Explicit {self.source} consent required")
        session.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": self.source + "-consent:" + scope(session)},
        )
        count = session.execute(
            sa.select(sa.func.count())
            .select_from(self.table)
            .where(
                self.table.c.workspace_id == scope(session),
                self.table.c.state != "revoked",
                self.table.c.expires_at > now(session),
            )
        ).scalar_one()
        if count >= 3:
            raise ValueError(f"{self.source} consent limit reached")
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        row = {
            "workspace_id": scope(session),
            "id": str(uuid4()),
            "created_by": session.info["actor_id"],
            "state": "pending",
            "state_hash": hashlib.sha256(state.encode()).hexdigest(),
            "configuration_hash": config.digest,
            "expires_at": now(session) + timedelta(minutes=10),
            "key_version": self.ring.active,
            "version": 1,
        }
        insert_row(
            session,
            self.table,
            **{k: v for k, v in row.items() if k != "workspace_id"},
            **self.seal(row, {"verifier": verifier}),
        )
        return {
            "consent_id": row["id"],
            "authorization_url": self.authorize(config, state, verifier),
            "expires_at": row["expires_at"],
        }

    def consume(self, session, config, identifier, state):
        row = self.get(session, identifier, lock=True)
        if (
            row["state"] != "pending"
            or row["expires_at"] <= now(session)
            or row["configuration_hash"] != config.digest
            or not hmac.compare_digest(
                row["state_hash"] or "", hashlib.sha256(state.encode()).hexdigest()
            )
        ):
            raise self.unavailable()
        verifier = self.open(row)["verifier"]
        version = row["version"] + 1
        session.execute(
            sa.update(self.table)
            .where(self.table.c.id == row["id"], self.table.c.workspace_id == scope(session))
            .values(state="exchanging", state_hash=None, ciphertext=b"", version=version)
        )
        return verifier, version

    def revoke(self, session, identifier):
        privacy_lock(session)
        row = self.get(session, identifier, lock=True)
        session.execute(
            sa.update(self.table)
            .where(self.table.c.workspace_id == scope(session), self.table.c.id == row["id"])
            .values(state="revoked", state_hash=None, ciphertext=b"", version=row["version"] + 1)
        )
        if row["connection_id"]:
            self.connections.revoke(session, UUID(row["connection_id"]))

    def activate(self, session, config, identifier, version, document):
        privacy_lock(session)
        row = self.get(session, identifier, lock=True)
        if (
            row["state"] != "exchanging"
            or row["version"] != version
            or row["expires_at"] <= now(session)
            or row["configuration_hash"] != config.digest
        ):
            raise self.unavailable()
        value = self.token_values(document)
        previous_id = row["connection_id"]
        if previous_id:
            previous = self.connections.metadata(session, UUID(previous_id))
            if previous.source != self.source or previous.state == "revoked":
                raise self.unavailable()
        expiry = min(
            now(session) + timedelta(seconds=value["expires_in"]),
            row["expires_at"] if previous_id else now(session) + timedelta(days=30),
        )
        reference = self.connections.create(
            session,
            self.source,
            "oauth",
            SecretPayload(credentials={"access_token": value["access_token"]}),
            expires_at=expiry,
            scopes=("read", "discover"),
        )
        row.update(state="active", connection_id=str(reference.id))
        if not previous_id:
            row["expires_at"] = now(session) + timedelta(days=30)
        session.execute(
            sa.update(self.table)
            .where(self.table.c.workspace_id == scope(session), self.table.c.id == row["id"])
            .values(
                state="active",
                connection_id=row["connection_id"],
                expires_at=row["expires_at"],
                **self.seal(row, {"refresh_token": value["refresh_token"]}),
            )
        )
        # Update the consent reference first: revocation of the retired access
        # connection must not invalidate the fresh consent generation.
        if previous_id:
            self.connections.revoke(session, UUID(previous_id))
        return reference

    def begin_refresh(self, session, config, identifier, *, expected_connection=None):
        privacy_lock(session)
        row = self.get(session, identifier, lock=True)
        if (
            row["state"] != "active"
            or row["expires_at"] <= now(session)
            or row["configuration_hash"] != config.digest
            or not row["connection_id"]
            or (
                expected_connection is not None and row["connection_id"] != str(expected_connection)
            )
        ):
            raise self.unavailable()
        reference = self.connections.metadata(session, UUID(row["connection_id"]))
        if reference.source != self.source or reference.state == "revoked":
            raise self.unavailable()
        refresh_token = self.open(row)["refresh_token"]
        version = row["version"] + 1
        session.execute(
            sa.update(self.table)
            .where(self.table.c.workspace_id == scope(session), self.table.c.id == row["id"])
            .values(state="exchanging", version=version, ciphertext=b"", state_hash=None)
        )
        return refresh_token, version


def complete_consent(database, store, config, provider, actor, workspace, identifier, state, code):
    # Commit consume before provider I/O. A lost/rotated token cannot be replayed.
    with database.tenant(actor, workspace) as session:
        verifier, version = store.consume(session, config, identifier, state)
    try:
        document = provider.exchange(config, code, verifier)
        with database.tenant(actor, workspace) as session:
            return store.activate(session, config, identifier, version, document)
    except Exception:  # noqa: BLE001 - revoke only our still-current uncertain generation
        invalidate(database, store, actor, workspace, identifier, version)
        raise store.unavailable() from None


def invalidate(database, store, actor, workspace, identifier, version):
    with database.tenant(actor, workspace) as session:
        privacy_lock(session)
        row = store.get(session, identifier, lock=True)
        if row["version"] == version and row["state"] == "exchanging":
            store.revoke(session, identifier)


def refresh_consent(
    database, store, config, provider, actor, workspace, identifier, *, expected_connection=None
):
    with database.tenant(actor, workspace) as session:
        refresh_token, version = store.begin_refresh(
            session, config, identifier, expected_connection=expected_connection
        )
    try:
        document = provider.refresh(config, refresh_token)
        with database.tenant(actor, workspace) as session:
            return store.activate(session, config, identifier, version, document)
    except Exception:  # noqa: BLE001 - uncertain rotation requires fresh user consent
        invalidate(database, store, actor, workspace, identifier, version)
        raise store.unavailable() from None
