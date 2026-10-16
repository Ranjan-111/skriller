"""New automation respects existing erasure and offline restore boundaries."""

import pytest
import sqlalchemy as sa
from test_webhooks import configure

from skriller.automation_lifecycle import quarantine
from skriller.erasure import erase
from skriller.lists import snapshot
from skriller.scheduling import create_schedule, schedules
from skriller.storage import EvidenceStorage, LocalBlobBackend
from skriller.webhooks.service import claim, deliver
from skriller.webhooks.tables import deliveries, endpoints

pytestmark = pytest.mark.integration_db


@pytest.fixture
def configured(database, monkeypatch):
    return configure(database, monkeypatch)


def test_erasure_invalidates_pending_notifications_before_deleting_snapshots(
    database, configured, tmp_path
):
    actor, workspace, saved, _, ring = configured
    with database.tenant(actor, workspace) as session:
        create_schedule(session, saved["id"], opt_in=True, cadence_hours=1, max_runs=1)
        entity = snapshot(session, saved["id"], 2)["payload"]["members"][0]["entity_id"]
        task = claim(session)
    with database.tenant(actor, workspace) as session:
        erase(
            session,
            EvidenceStorage(LocalBlobBackend(tmp_path / "objects")),
            entity,
            request_key="fixture-erase",
        )
        assert session.execute(sa.select(deliveries)).all() == []
        assert session.execute(sa.select(endpoints.c.enabled)).scalar_one() is False
        assert session.execute(sa.select(schedules.c.last_reason)).scalar_one() == "data_erasure"
    with database.tenant(actor, workspace) as session:
        assert (
            deliver(session, task, ring, send=lambda *_: pytest.fail("erased notification"))
            == "stale_lease"
        )


def test_restore_quarantine_preserves_history_but_never_replays_old_opt_in(database, configured):
    actor, workspace, saved, _, ring = configured
    with database.tenant(actor, workspace) as session:
        create_schedule(session, saved["id"], opt_in=True, cadence_hours=1, max_runs=1)
        task = claim(session)
    with database.tenant(actor, workspace) as session:
        quarantine(session, "restore_requires_opt_in")
        assert session.execute(sa.select(deliveries.c.state)).scalar_one() == "cancelled"
        assert session.execute(sa.select(endpoints.c.enabled)).scalar_one() is False
        assert session.execute(sa.select(schedules.c.enabled)).scalar_one() is False
        assert claim(session) is None
        assert (
            deliver(session, task, ring, send=lambda *_: pytest.fail("restored notification"))
            == "stale_lease"
        )
