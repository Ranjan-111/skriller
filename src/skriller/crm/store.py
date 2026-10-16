"""Owner-bound encrypted Salesforce destinations; no browser/session extraction.

Uses the existing connection Keyring and the same AES-GCM/AAD pattern as the
owner-bound AnalyticsStore, with a distinct CRM domain and generation fence.
"""

import json
import os
from datetime import UTC, timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from skriller.connections.keys import Keyring
from skriller.crm.salesforce import SalesforceUnavailable, validate_instance
from skriller.db.repositories import insert_row, require_owner, scope
from skriller.db.schema import scoped

destinations = scoped(
    "crm_destinations",
    sa.Column("created_by", sa.String(128), nullable=False),
    sa.Column("instance_url", sa.String(160), nullable=False),
    sa.Column("enabled", sa.Boolean, nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("key_version", sa.String(64), nullable=False),
    sa.Column("nonce", sa.LargeBinary, nullable=False),
    sa.Column("ciphertext", sa.LargeBinary, nullable=False),
    sa.Column("generation", sa.Integer, nullable=False, server_default="1"),
)


def public(row):
    return {key: row[key] for key in ("id", "instance_url", "enabled", "expires_at", "generation")}


class DestinationStore:
    def __init__(self, keyring: Keyring):
        self.keyring = keyring

    @staticmethod
    def _aad(row):
        return json.dumps(
            [
                "skriller-crm-destination-v1",
                row["workspace_id"],
                row["id"],
                row["created_by"],
                row["instance_url"],
                row["key_version"],
                row["generation"],
                row["expires_at"].astimezone(UTC).isoformat(),
            ],
            separators=(",", ":"),
        ).encode()

    def get(self, session, identifier, *, lock=False):
        require_owner(session)
        query = sa.select(destinations).where(
            destinations.c.workspace_id == scope(session),
            destinations.c.id == str(UUID(str(identifier))),
            destinations.c.created_by == session.info["actor_id"],
        )
        if lock:
            query = query.with_for_update()
        row = session.execute(query).mappings().one_or_none()
        if row is None:
            raise SalesforceUnavailable()
        return row

    def create(self, session, instance_url, access_token, *, expires_at, opt_in=False):
        """Short-lived explicitly supplied token; OAuth acquisition remains separate."""
        require_owner(session)
        instance_url = validate_instance(instance_url)
        now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
        if (
            opt_in is not True
            or expires_at.tzinfo is None
            or not now + timedelta(seconds=30) < expires_at <= now + timedelta(hours=1)
            or not isinstance(access_token, str)
            or not 16 <= len(access_token) <= 8192
            or any(not 33 <= ord(char) <= 126 for char in access_token)
        ):
            raise ValueError("Explicit CRM opt-in and bounded token validity required")
        session.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "crm-destinations:" + scope(session)},
        )
        count = session.execute(
            sa.select(sa.func.count())
            .select_from(destinations)
            .where(destinations.c.workspace_id == scope(session), destinations.c.enabled.is_(True))
        ).scalar_one()
        if count >= 3:
            raise ValueError("CRM destination limit reached")
        row = {
            "workspace_id": scope(session),
            "id": str(uuid4()),
            "created_by": session.info["actor_id"],
            "instance_url": instance_url,
            "key_version": self.keyring.active,
            "generation": 1,
            "expires_at": expires_at,
        }
        nonce = os.urandom(12)
        ciphertext = AESGCM(self.keyring.keys[self.keyring.active]).encrypt(
            nonce, access_token.encode(), self._aad(row)
        )
        return public(
            insert_row(
                session,
                destinations,
                **{key: value for key, value in row.items() if key != "workspace_id"},
                nonce=nonce,
                ciphertext=ciphertext,
                enabled=True,
            )
        )

    def credentials(self, session, identifier, *, generation):
        row = self.get(session, identifier, lock=True)
        now = session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
        if (
            not row["enabled"]
            or row["generation"] != generation
            or row["expires_at"] <= now + timedelta(seconds=15)
        ):
            raise SalesforceUnavailable()
        try:
            token = (
                AESGCM(self.keyring.keys[row["key_version"]])
                .decrypt(row["nonce"], row["ciphertext"], self._aad(row))
                .decode()
            )
            return validate_instance(row["instance_url"]), token
        except Exception:  # noqa: BLE001 - never echo ciphertext/key/remote credentials
            raise SalesforceUnavailable() from None

    def revoke(self, session, identifier):
        from skriller.crm.queue import deliveries
        from skriller.erasure import privacy_lock

        # Serialize the destination/queue locks with delivery and erasure.
        privacy_lock(session)
        row = self.get(session, identifier, lock=True)
        session.execute(
            sa.update(destinations)
            .where(destinations.c.workspace_id == scope(session), destinations.c.id == row["id"])
            .values(enabled=False, ciphertext=b"", generation=row["generation"] + 1)
        )
        session.execute(
            sa.update(deliveries)
            .where(
                deliveries.c.workspace_id == scope(session),
                deliveries.c.destination_id == row["id"],
                deliveries.c.state.in_(("pending", "delivering")),
            )
            .values(
                state="cancelled",
                last_code="destination_revoked",
                lease_token=None,
                lease_expires_at=None,
            )
        )
