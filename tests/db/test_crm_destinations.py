from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from skriller.connections.keys import Keyring
from skriller.crm.salesforce import SalesforceUnavailable
from skriller.crm.store import DestinationStore, destinations
from skriller.db import WorkspaceRepository

pytestmark = pytest.mark.integration_db


def setup(database):
    actor = "crm-store-" + uuid4().hex
    workspace = database.create_workspace(actor, "CRM store")["id"]
    store = DestinationStore(Keyring("fixture", {"fixture": AESGCM.generate_key(bit_length=256)}))
    return actor, workspace, store


def create(store, session, **changes):
    args = {
        "instance_url": "https://fixture.my.salesforce.com",
        "access_token": "fixture-access-token-only",
        "expires_at": datetime.now(UTC) + timedelta(minutes=30),
        "opt_in": True,
    } | changes
    return store.create(session, **args)


def test_encrypted_at_rest_owner_scope_and_generation_revocation(database):
    actor, workspace, store = setup(database)
    with database.tenant(actor, workspace) as session:
        row = create(store, session)
        assert not {"ciphertext", "nonce", "access_token", "key_version"} & row.keys()
        stored = store.get(session, row["id"])
        assert b"fixture-access-token" not in stored["ciphertext"]
        assert store.credentials(session, row["id"], generation=1) == (
            "https://fixture.my.salesforce.com",
            "fixture-access-token-only",
        )
        WorkspaceRepository.add_member(session, actor + "-coowner", role="owner")
    with (
        database.tenant(actor + "-coowner", workspace) as session,
        pytest.raises(SalesforceUnavailable),
    ):
        store.credentials(session, row["id"], generation=1)
    other = database.create_workspace(actor, "Other scope")["id"]
    with database.tenant(actor, other) as session, pytest.raises(SalesforceUnavailable):
        store.credentials(session, row["id"], generation=1)
    with database.tenant(actor, workspace) as session:
        store.revoke(session, row["id"])
        assert store.get(session, row["id"])["ciphertext"] == b""
        with pytest.raises(SalesforceUnavailable):
            store.credentials(session, row["id"], generation=1)


def test_tampered_destination_expired_token_and_wrong_key_fail_closed(database):
    actor, workspace, store = setup(database)
    with database.tenant(actor, workspace) as session:
        row = create(store, session)
        wrong = DestinationStore(
            Keyring("fixture", {"fixture": AESGCM.generate_key(bit_length=256)})
        )
        with pytest.raises(SalesforceUnavailable):
            wrong.credentials(session, row["id"], generation=1)
        session.execute(
            sa.update(destinations)
            .where(destinations.c.id == row["id"])
            .values(instance_url="https://changed.my.salesforce.com")
        )
        with pytest.raises(SalesforceUnavailable):
            store.credentials(session, row["id"], generation=1)
        session.execute(
            sa.update(destinations)
            .where(destinations.c.id == row["id"])
            .values(instance_url="https://fixture.my.salesforce.com", expires_at=datetime.now(UTC))
        )
        with pytest.raises(SalesforceUnavailable):
            store.credentials(session, row["id"], generation=1)


@pytest.mark.parametrize(
    "changes",
    [
        {"opt_in": False},
        {"expires_at": datetime.now(UTC) + timedelta(days=1)},
        {"access_token": "invalid\ncredential"},
        {"instance_url": "https://127.0.0.1"},
    ],
)
def test_explicit_bounded_configuration_required(database, changes):
    actor, workspace, store = setup(database)
    with (
        database.tenant(actor, workspace) as session,
        pytest.raises((ValueError, SalesforceUnavailable)),
    ):
        create(store, session, **changes)
