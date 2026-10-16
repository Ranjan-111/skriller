"""Owner-only CRM OAuth lifecycle, adapted from analytics.service grant fences."""

import hashlib
import hmac
import json
import os
import secrets
from datetime import UTC, timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from skriller.crm.oauth import authorization_url, tokens
from skriller.crm.salesforce import SalesforceUnavailable
from skriller.crm.store import destinations
from skriller.db.repositories import insert_row, require_owner, scope
from skriller.db.schema import scoped
from skriller.erasure import privacy_lock

consents = scoped(
    "crm_oauth_consents",
    sa.Column("created_by", sa.String(128), nullable=False),
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("state_hash", sa.String(64)),
    sa.Column("configuration_hash", sa.String(64), nullable=False),
    sa.Column("destination_id", sa.Uuid(as_uuid=False)),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("key_version", sa.String(64), nullable=False),
    sa.Column("nonce", sa.LargeBinary, nullable=False),
    sa.Column("ciphertext", sa.LargeBinary, nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
)


def now(session):
    return session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()


class ConsentStore:
    def __init__(self, destinations_store):
        self.destinations = destinations_store
        self.ring = destinations_store.keyring

    @staticmethod
    def _aad(row):
        return json.dumps(
            [
                "skriller-crm-oauth-v1",
                row["workspace_id"],
                row["id"],
                row["created_by"],
                row["configuration_hash"],
                row.get("destination_id"),
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
            raise SalesforceUnavailable() from None

    def get(self, session, identifier, *, lock=False):
        require_owner(session)
        query = sa.select(consents).where(
            consents.c.workspace_id == scope(session),
            consents.c.id == str(UUID(str(identifier))),
            consents.c.created_by == session.info["actor_id"],
        )
        if lock:
            query = query.with_for_update()
        row = session.execute(query).mappings().one_or_none()
        if row is None:
            raise SalesforceUnavailable()
        return dict(row)

    def start(self, session, config, *, opt_in):
        require_owner(session)
        if opt_in is not True:
            raise ValueError("Explicit CRM consent required")
        session.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "crm-consent:" + scope(session)},
        )
        count = session.execute(
            sa.select(sa.func.count())
            .select_from(consents)
            .where(
                consents.c.workspace_id == scope(session),
                consents.c.state != "revoked",
                consents.c.expires_at > now(session),
            )
        ).scalar_one()
        if count >= 3:
            raise ValueError("CRM consent limit reached")
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
            consents,
            **{k: v for k, v in row.items() if k != "workspace_id"},
            **self.seal(row, {"verifier": verifier}),
        )
        return {
            "consent_id": row["id"],
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
            raise SalesforceUnavailable()
        verifier = self.open(row)["verifier"]
        version = row["version"] + 1
        session.execute(
            sa.update(consents)
            .where(consents.c.id == row["id"], consents.c.workspace_id == scope(session))
            .values(state="exchanging", state_hash=None, ciphertext=b"", version=version)
        )
        return verifier, version

    def revoke(self, session, identifier):
        privacy_lock(session)
        row = self.get(session, identifier, lock=True)
        if row["destination_id"]:
            self.destinations.revoke(session, row["destination_id"])
        session.execute(
            sa.update(consents)
            .where(consents.c.id == row["id"], consents.c.workspace_id == scope(session))
            .values(state="revoked", state_hash=None, ciphertext=b"", version=row["version"] + 1)
        )

    def activate(self, session, config, identifier, version, document):
        privacy_lock(session)
        row = self.get(session, identifier, lock=True)
        if (
            row["state"] != "exchanging"
            or row["version"] != version
            or row["expires_at"] <= now(session)
            or row["configuration_hash"] != config.digest
        ):
            raise SalesforceUnavailable()
        value = tokens(document)
        destination = self.destinations.create(
            session,
            value["instance_url"],
            value["access_token"],
            expires_at=now(session) + timedelta(minutes=15),
            opt_in=True,
        )
        row.update(
            state="active",
            destination_id=destination["id"],
            expires_at=now(session) + timedelta(days=30),
        )
        session.execute(
            sa.update(consents)
            .where(consents.c.id == row["id"], consents.c.workspace_id == scope(session))
            .values(
                state="active",
                destination_id=destination["id"],
                expires_at=row["expires_at"],
                **self.seal(row, value),
            )
        )
        return destination

    def begin_refresh(self, session, config, destination_id):
        privacy_lock(session)
        row = (
            session.execute(
                sa.select(consents)
                .where(
                    consents.c.workspace_id == scope(session),
                    consents.c.destination_id == str(destination_id),
                    consents.c.created_by == session.info["actor_id"],
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None  # explicitly supplied short-lived internal token, not OAuth
        row = dict(row)
        destination = self.destinations.get(session, destination_id, lock=True)
        if (
            row["state"] != "active"
            or row["expires_at"] <= now(session)
            or row["configuration_hash"] != config.digest
            or not destination["enabled"]
        ):
            raise SalesforceUnavailable()
        if destination["expires_at"] > now(session) + timedelta(minutes=2):
            return None
        value = self.open(row)
        row["version"] += 1
        session.execute(
            sa.update(consents)
            .where(consents.c.workspace_id == scope(session), consents.c.id == row["id"])
            .values(state="exchanging", version=row["version"], ciphertext=b"")
        )
        return row["id"], row["version"], value

    def finish_refresh(self, session, config, identifier, version, document):
        privacy_lock(session)
        row = self.get(session, identifier, lock=True)
        if (
            row["state"] != "exchanging"
            or row["version"] != version
            or row["expires_at"] <= now(session)
            or row["configuration_hash"] != config.digest
        ):
            raise SalesforceUnavailable()
        destination = dict(self.destinations.get(session, row["destination_id"], lock=True))
        value = tokens(document)
        if not destination["enabled"] or value["instance_url"] != destination["instance_url"]:
            raise SalesforceUnavailable()
        destination["expires_at"] = min(now(session) + timedelta(minutes=15), row["expires_at"])
        nonce = os.urandom(12)
        encrypted = AESGCM(self.ring.keys[destination["key_version"]]).encrypt(
            nonce, value["access_token"].encode(), self.destinations._aad(destination)
        )
        # Preserve destination generation: routine rotation must not invalidate
        # selections already queued for this exact authorised connection.
        session.execute(
            sa.update(destinations)
            .where(
                destinations.c.workspace_id == scope(session),
                destinations.c.id == destination["id"],
            )
            .values(expires_at=destination["expires_at"], nonce=nonce, ciphertext=encrypted)
        )
        session.execute(
            sa.update(consents)
            .where(consents.c.workspace_id == scope(session), consents.c.id == row["id"])
            .values(state="active", **self.seal(row, value))
        )


def refresh_destination(database, store, config, provider, actor, workspace, destination_id):
    with database.tenant(actor, workspace) as session:
        require_owner(session)
        pending = store.begin_refresh(session, config, destination_id)
    if pending is None:
        return
    identifier, version, value = pending
    try:
        document = provider.refresh(config, value["refresh_token"])
        with database.tenant(actor, workspace) as session:
            store.finish_refresh(session, config, identifier, version, document)
    except Exception:  # noqa: BLE001 - an uncertain rotated refresh token is not replayed
        with database.tenant(actor, workspace) as session:
            row = store.get(session, identifier)
            if row["version"] == version and row["state"] == "exchanging":
                store.revoke(session, identifier)
        raise SalesforceUnavailable() from None
