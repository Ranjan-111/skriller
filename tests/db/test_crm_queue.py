from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from test_crm_preparation import MAPPING, crm_fixture

from skriller.connections.keys import Keyring
from skriller.crm.queue import claim, deliver, deliveries, enqueue
from skriller.crm.salesforce import SalesforceUnavailable
from skriller.crm.store import DestinationStore
from skriller.erasure import erase

pytestmark = pytest.mark.integration_db


def setup(database, tmp_path):
    actor, workspace, a, b, plan, storage = crm_fixture(database, tmp_path)
    store = DestinationStore(Keyring("fixture", {"fixture": AESGCM.generate_key(bit_length=256)}))
    with database.tenant(actor, workspace) as session:
        destination = store.create(
            session,
            "https://fixture.my.salesforce.com",
            "fixture-crm-access-token",
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
            opt_in=True,
        )
    return actor, workspace, a, b, plan, storage, store, destination["id"]


def queue(session, storage, store, destination, plan, entity, **changes):
    args = {"field_map": MAPPING, "idempotency_key": "fixture-one", "opt_in": True} | changes
    return enqueue(session, storage, store, destination, plan, entity, **args)


def test_real_queue_idempotency_retry_and_fresh_qualified_upsert(database, tmp_path):
    actor, workspace, a, _, plan, storage, store, destination = setup(database, tmp_path)
    with database.tenant(actor, workspace) as session:
        first = queue(session, storage, store, destination, plan, a)
        assert first == queue(session, storage, store, destination, plan, a)
        with pytest.raises(ValueError, match="different intent"):
            queue(session, storage, store, destination, plan, a, selected_near=True)
    with database.tenant(actor, workspace) as session:
        task = claim(session)
    calls = []

    def timeout(instance, token, lead):
        calls.append(lead)
        raise SalesforceUnavailable()

    with database.tenant(actor, workspace) as session:
        assert deliver(session, task, storage, store, send=timeout) == "pending"
        session.execute(
            sa.update(deliveries)
            .where(deliveries.c.id == first["id"])
            .values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    with database.tenant(actor, workspace) as session:
        retry = claim(session)

    def success(instance, token, lead):
        calls.append(lead)
        assert lead.fields["Skriller_Fit__c"] == "confirmed" and "Email" not in lead.fields
        return "updated"

    with database.tenant(actor, workspace) as session:
        assert deliver(session, task, storage, store, send=success) == "stale"
        assert deliver(session, retry, storage, store, send=success) == "succeeded"
        assert claim(session) is None
    assert len(calls) == 2 and calls[0].external_id == calls[1].external_id


def test_erasure_after_claim_prevents_any_crm_send(database, tmp_path):
    actor, workspace, a, _, plan, storage, store, destination = setup(database, tmp_path)
    with database.tenant(actor, workspace) as session:
        queue(session, storage, store, destination, plan, a)
    with database.tenant(actor, workspace) as session:
        task = claim(session)
    with database.tenant(actor, workspace) as session:
        erase(session, storage, a, request_key="erase-before-crm-delivery")
    with database.tenant(actor, workspace) as session:
        assert (
            deliver(
                session,
                task,
                storage,
                store,
                send=lambda *args: pytest.fail("Suppressed entity sent"),
            )
            == "suppressed"
        )


def test_revoked_destination_and_near_match_selection_remain_enforced(database, tmp_path):
    actor, workspace, _, b, plan, storage, store, destination = setup(database, tmp_path)
    with database.tenant(actor, workspace) as session:
        with pytest.raises(ValueError, match="Only confirmed"):
            queue(session, storage, store, destination, plan, b)
        queue(session, storage, store, destination, plan, b, selected_near=True)
    with database.tenant(actor, workspace) as session:
        task = claim(session)
    with database.tenant(actor, workspace) as session:
        store.revoke(session, destination)
    with database.tenant(actor, workspace) as session:
        assert (
            deliver(
                session,
                task,
                storage,
                store,
                send=lambda *args: pytest.fail("Revoked destination used"),
            )
            == "stale"
        )


def test_actual_bounded_crm_child_rejects_missing_delivery_without_provider_access(
    database, tmp_path, monkeypatch
):
    from uuid import uuid4

    from skriller.crm.runtime import run_delivery_child

    actor, workspace, _, _, _, _, _, _ = setup(database, tmp_path)
    path = tmp_path / "child-keys" / "keyring.json"
    Keyring.create_file(path)
    monkeypatch.setenv("SKRILLER_SOURCE_ENCRYPTION_KEY_FILE", str(path))
    task = {"id": str(uuid4()), "lease_token": str(uuid4())}
    assert run_delivery_child(actor, workspace, task) == "stale"


def test_provider_early_401_makes_access_due_for_next_attempt_refresh(database, tmp_path):
    from skriller.crm.salesforce import SalesforceAuthorizationExpired

    actor, workspace, a, _, plan, storage, store, destination = setup(database, tmp_path)
    with database.tenant(actor, workspace) as session:
        queue(session, storage, store, destination, plan, a)
    with database.tenant(actor, workspace) as session:
        task = claim(session)

    def expired(*args):
        raise SalesforceAuthorizationExpired()

    with database.tenant(actor, workspace) as session:
        assert deliver(session, task, storage, store, send=expired) == "pending"
        row = store.get(session, destination)
        assert (
            row["expires_at"] <= session.execute(sa.select(sa.func.clock_timestamp())).scalar_one()
        )
        with pytest.raises(SalesforceUnavailable):
            store.credentials(session, destination, generation=row["generation"])
