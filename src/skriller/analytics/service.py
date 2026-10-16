"""Owner-bound, single-use OAuth completion and encrypted grant lifecycle."""

import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from skriller.analytics.google import (
    SCOPES,
    AnalyticsUnavailable,
    OAuthConfiguration,
    authorization_url,
    validate_tokens,
)
from skriller.analytics.tables import grants
from skriller.connections.keys import Keyring
from skriller.db.repositories import insert_row, require_owner, scope


def now(session):
    return session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()


def public(row, current_time):
    state = row["state"]
    if state != "revoked" and (
        row["expires_at"] <= current_time
        or (state == "active" and row["access_expires_at"] <= current_time)
    ):
        state = "expired"
    return {
        key: row[key]
        for key in (
            "id",
            "workspace_id",
            "created_by",
            "channel_id",
            "scopes",
            "expires_at",
            "access_expires_at",
        )
    } | {"state": state, "remote_revocation": "not_performed"}


class AnalyticsStore:
    def __init__(self, ring: Keyring):
        self.ring = ring

    @staticmethod
    def _aad(row):
        return json.dumps(
            [
                "skriller-youtube-analytics-v1",
                row["workspace_id"],
                row["id"],
                row["created_by"],
                row["configuration_hash"],
                row["key_version"],
                row["version"],
            ],
            separators=(",", ":"),
        ).encode()

    def _encrypt(self, row, value):
        nonce = os.urandom(12)
        return {
            "nonce": nonce,
            "ciphertext": AESGCM(self.ring.keys[row["key_version"]]).encrypt(
                nonce, json.dumps(value).encode(), self._aad(row)
            ),
        }

    def _decrypt(self, row):
        try:
            return json.loads(
                AESGCM(self.ring.keys[row["key_version"]]).decrypt(
                    row["nonce"], row["ciphertext"], self._aad(row)
                )
            )
        except Exception:  # noqa: BLE001 - secret metadata never leaks on key/tamper failures
            raise AnalyticsUnavailable() from None

    def get(self, session, identifier, *, lock=False):
        require_owner(session)
        query = sa.select(grants).where(
            grants.c.workspace_id == scope(session),
            grants.c.id == str(UUID(str(identifier))),
            grants.c.created_by == session.info["actor_id"],
        )
        if lock:
            query = query.with_for_update()
        row = session.execute(query).mappings().one_or_none()
        if row is None:
            raise AnalyticsUnavailable()
        return dict(row)

    def start(self, session, config: OAuthConfiguration, *, opt_in: bool):
        require_owner(session)
        if opt_in is not True:
            raise ValueError("Explicit owner analytics opt-in required")
        session.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "analytics:" + scope(session)},
        )
        current = now(session)
        count = session.execute(
            sa.select(sa.func.count())
            .select_from(grants)
            .where(
                grants.c.workspace_id == scope(session),
                grants.c.state != "revoked",
                grants.c.expires_at > current,
            )
        ).scalar_one()
        if count >= 10:
            raise ValueError("Owner analytics grant limit reached")
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        values = {
            "workspace_id": scope(session),
            "id": str(uuid4()),
            "created_by": session.info["actor_id"],
            "state": "pending",
            "state_hash": hashlib.sha256(state.encode()).hexdigest(),
            "configuration_hash": config.digest,
            "scopes": list(SCOPES),
            "expires_at": current + timedelta(minutes=10),
            "key_version": self.ring.active,
            "version": 1,
        }
        encrypted = self._encrypt(values, {"verifier": verifier})
        row = insert_row(
            session, grants, **{k: v for k, v in values.items() if k != "workspace_id"}, **encrypted
        )
        return {
            "grant_id": row["id"],
            "authorization_url": authorization_url(config, state, verifier),
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
            raise AnalyticsUnavailable("analytics_consent_expired_or_invalid")
        verifier = self._decrypt(row)["verifier"]
        session.execute(
            sa.update(grants)
            .where(grants.c.workspace_id == scope(session), grants.c.id == row["id"])
            .values(state="exchanging", state_hash=None, ciphertext=b"", version=row["version"] + 1)
        )
        return verifier, row["version"] + 1

    def activate(self, session, config, identifier, version, tokens, channel_id):
        credentials = validate_tokens(tokens)
        if not isinstance(channel_id, str) or not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", channel_id):
            raise AnalyticsUnavailable("analytics_owner_channel_unavailable")
        row = self.get(session, identifier, lock=True)
        current = now(session)
        if (
            row["state"] != "exchanging"
            or row["version"] != version
            or row["configuration_hash"] != config.digest
            or row["expires_at"] <= current
        ):
            raise AnalyticsUnavailable("analytics_consent_expired_or_invalid")
        row.update(version=version + 1, key_version=self.ring.active)
        session.execute(
            sa.update(grants)
            .where(grants.c.workspace_id == scope(session), grants.c.id == row["id"])
            .values(
                state="active",
                channel_id=channel_id,
                scopes=list(SCOPES),
                expires_at=current + timedelta(days=30),
                access_expires_at=current + timedelta(seconds=tokens["expires_in"]),
                version=row["version"],
                key_version=row["key_version"],
                **self._encrypt(row, credentials),
            )
        )
        return public(self.get(session, identifier), current)

    def revoke(self, session, identifier):
        row = self.get(session, identifier, lock=True)
        session.execute(
            sa.update(grants)
            .where(grants.c.workspace_id == scope(session), grants.c.id == row["id"])
            .values(
                state="revoked",
                state_hash=None,
                ciphertext=b"",
                version=row["version"] + 1,
            )
        )
        return public(self.get(session, identifier), now(session))

    def access(self, session, identifier):
        row = self.get(session, identifier)
        current = now(session)
        if (
            row["state"] != "active"
            or row["expires_at"] <= current
            or row["access_expires_at"] <= current
            or set(row["scopes"]) != set(SCOPES)
        ):
            raise AnalyticsUnavailable()
        return row, self._decrypt(row)["access_token"]

    def recheck(self, session, identifier, version):
        row, _ = self.access(session, identifier)
        if row["version"] != version:
            raise AnalyticsUnavailable()

    def begin_refresh(self, session, config, identifier):
        row = self.get(session, identifier, lock=True)
        if (
            row["state"] != "active"
            or row["expires_at"] <= now(session)
            or row["configuration_hash"] != config.digest
            or set(row["scopes"]) != set(SCOPES)
        ):
            raise AnalyticsUnavailable()
        credentials = self._decrypt(row)
        refresh_token = credentials.get("refresh_token")
        if not refresh_token:
            raise AnalyticsUnavailable("analytics_renewed_consent_required")
        row["version"] += 1
        row["key_version"] = self.ring.active
        session.execute(
            sa.update(grants)
            .where(grants.c.workspace_id == scope(session), grants.c.id == row["id"])
            .values(
                state="exchanging",
                version=row["version"],
                key_version=row["key_version"],
                **self._encrypt(row, credentials),
            )
        )
        return refresh_token, row["version"]

    def finish_refresh(self, session, config, identifier, version, tokens):
        credentials = validate_tokens(tokens)
        row = self.get(session, identifier, lock=True)
        current = now(session)
        if (
            row["state"] != "exchanging"
            or row["version"] != version
            or row["expires_at"] <= current
            or row["configuration_hash"] != config.digest
        ):
            raise AnalyticsUnavailable()
        row.update(version=version + 1, key_version=self.ring.active)
        session.execute(
            sa.update(grants)
            .where(grants.c.workspace_id == scope(session), grants.c.id == row["id"])
            .values(
                state="active",
                version=row["version"],
                key_version=row["key_version"],
                access_expires_at=current + timedelta(seconds=tokens["expires_in"]),
                **self._encrypt(row, credentials),
            )
        )
        return public(self.get(session, identifier), current)


def purge_expired(session):
    """Erase expired secrets across grant owners; privileged SQL returns no data."""
    require_owner(session)
    session.execute(sa.text("SELECT expire_youtube_analytics_grants()"))
    session.execute(sa.text("SELECT expire_analytics_summary_snapshots()"))


def refresh_grant(database, store, config, provider, actor, workspace, identifier):
    with database.tenant(actor, workspace) as session:
        refresh_token, version = store.begin_refresh(session, config, identifier)
    try:
        tokens = provider.refresh(config, refresh_token)
        with database.tenant(actor, workspace) as session:
            return store.finish_refresh(session, config, identifier, version, tokens)
    except Exception:  # noqa: BLE001 - no provider or credential details escape
        with database.tenant(actor, workspace) as session:
            row = store.get(session, identifier, lock=True)
            if row["state"] == "exchanging" and row["version"] == version:
                store.revoke(session, identifier)
        raise AnalyticsUnavailable("analytics_refresh_failed") from None
