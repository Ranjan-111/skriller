"""Encrypted report snapshots cannot cross owners or survive revoked consent."""

from dataclasses import replace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from test_saved_graph import context_for
from test_youtube_analytics_reports import REQUEST, ReportsProvider, connected

from skriller.analytics.google import AnalyticsUnavailable
from skriller.analytics.private_jobs import PrivateSummaryStore
from skriller.analytics.reports import ReportRequest, read_report
from skriller.analytics.router import configuration
from skriller.analytics.tables import summary_jobs
from skriller.db import WorkspaceRepository

pytestmark = pytest.mark.integration_db


def fixture(database):
    context = context_for(database)
    actor, workspace, app, _, _, identifier = connected(
        database, ReportsProvider(), owner=context.actor_id, workspace=str(context.workspace_id)
    )
    verified = read_report(
        database,
        app.state.analytics_store,
        configuration(type("Request", (), {"app": app})()),
        app.state.analytics_provider,
        actor,
        workspace,
        identifier,
        ReportRequest.model_validate(REQUEST),
    )
    return context, app.state.analytics_store, verified


def test_snapshot_encrypted_idempotent_owner_bound_and_revoke_wipes(database):
    context, grants, verified = fixture(database)
    store = PrivateSummaryStore(grants)
    actor, workspace, job = context.actor_id, str(context.workspace_id), str(context.job_id)
    other = "co-owner-" + str(uuid4())
    with database.tenant(actor, workspace) as session:
        row = store.save(session, job, verified)
        assert b"views" not in row["ciphertext"] and b"120" not in row["ciphertext"]
        assert store.report(session, job) == verified
        assert store.save(session, job, verified)["id"] == job
        WorkspaceRepository.add_member(session, other, "owner")
        changed = replace(
            verified, report=verified.report.model_copy(update={"summary": ["wrong"]})
        )
        with pytest.raises(ValueError, match="already bound"):
            store.save(session, job, changed)
    with database.tenant(other, workspace) as session:
        assert session.execute(sa.select(summary_jobs)).mappings().all() == []
        with pytest.raises(AnalyticsUnavailable):
            store.report(session, job)
    with database.tenant(actor, workspace) as session:
        grants.revoke(session, verified.report.grant_id)
        row = (
            session.execute(sa.select(summary_jobs).where(summary_jobs.c.id == job))
            .mappings()
            .one()
        )
        assert row["ciphertext"] == b"" and row["state"] == "cancelled"
        with pytest.raises(AnalyticsUnavailable):
            store.report(session, job)


def test_snapshot_tampered_expiry_or_ciphertext_fails_closed(database):
    context, grants, verified = fixture(database)
    store = PrivateSummaryStore(grants)
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        store.save(session, str(context.job_id), verified)
        session.execute(
            sa.update(summary_jobs)
            .where(summary_jobs.c.id == str(context.job_id))
            .values(expires_at=sa.func.now() + sa.text("interval '2 hours'"))
        )
        with pytest.raises(AnalyticsUnavailable):
            store.report(session, str(context.job_id))


async def test_private_execution_charges_once_and_returns_exact_encrypted_result(database):
    from uuid import NAMESPACE_URL, uuid5

    from test_youtube_analytics_reports import SummaryStub

    from skriller.extraction.models import LocalStructuredModel
    from skriller.jobs.budget import current_usage

    context, grants, verified = fixture(database)
    store = PrivateSummaryStore(grants)
    job = str(context.job_id)
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        store.save(session, job, verified)
    stub = SummaryStub(
        str(uuid5(NAMESPACE_URL, verified.report.response_sha256 + ":0")),
        verified.report.summary[0],
    )
    model = LocalStructuredModel(model_instance=stub)
    assert await store.execute(database, context, model=model) == "completed"
    assert await store.execute(database, context, model=model) == "completed"
    assert stub.calls == 1
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        result = store.result(session, job)
        assert result["result"]["observations"][0]["quote"] == verified.report.summary[0]
        assert current_usage(session, job)[1]["llm_calls"] == 1


async def test_cancel_during_model_io_discards_answer(database):
    from uuid import NAMESPACE_URL, uuid5

    from test_youtube_analytics_reports import SummaryStub

    from skriller.extraction.models import LocalStructuredModel

    context, grants, verified = fixture(database)
    store = PrivateSummaryStore(grants)
    job, workspace = str(context.job_id), str(context.workspace_id)
    with database.tenant(context.actor_id, workspace) as session:
        store.save(session, job, verified)

    def cancel():
        with database.tenant(context.actor_id, workspace) as session:
            store.cancel(session, job)

    stub = SummaryStub(
        str(uuid5(NAMESPACE_URL, verified.report.response_sha256 + ":0")),
        verified.report.summary[0],
        hook=cancel,
    )
    assert (
        await store.execute(database, context, model=LocalStructuredModel(model_instance=stub))
        == "cancelled"
    )
    with database.tenant(context.actor_id, workspace) as session:
        assert store.result(session, job) == {"state": "cancelled", "result": None}


def test_expired_snapshots_wiped_by_other_owner_retention(database):
    from skriller.analytics.service import purge_expired

    context, grants, verified = fixture(database)
    store = PrivateSummaryStore(grants)
    job, workspace = str(context.job_id), str(context.workspace_id)
    other = "retention-owner-" + str(uuid4())
    with database.tenant(context.actor_id, workspace) as session:
        store.save(session, job, verified)
        WorkspaceRepository.add_member(session, other, "owner")
        session.execute(
            sa.update(summary_jobs)
            .where(summary_jobs.c.id == job)
            .values(expires_at=sa.func.now() - sa.text("interval '1 second'"))
        )
    with database.tenant(other, workspace) as session:
        purge_expired(session)
    with database.tenant(context.actor_id, workspace) as session:
        row = (
            session.execute(sa.select(summary_jobs).where(summary_jobs.c.id == job))
            .mappings()
            .one()
        )
        assert row["ciphertext"] == b"" and row["state"] == "cancelled"


def test_snapshot_rejects_wrong_key_and_noninitiating_job_owner(database):
    from skriller.analytics.service import AnalyticsStore
    from skriller.connections.keys import Keyring

    context, grants, verified = fixture(database)
    workspace, job = str(context.workspace_id), str(context.job_id)
    store = PrivateSummaryStore(grants)
    with database.tenant(context.actor_id, workspace) as session:
        store.save(session, job, verified)
        wrong = PrivateSummaryStore(AnalyticsStore(Keyring("v1", {"v1": b"z" * 32})))
        with pytest.raises(AnalyticsUnavailable):
            wrong.report(session, job)
        with pytest.raises(AnalyticsUnavailable):
            store.save(session, job, replace(verified, owner_id="another-owner"))


async def test_revoke_during_private_execution_wipes_snapshot(database):
    from uuid import NAMESPACE_URL, uuid5

    from test_youtube_analytics_reports import SummaryStub

    from skriller.extraction.models import LocalStructuredModel

    context, grants, verified = fixture(database)
    store = PrivateSummaryStore(grants)
    workspace, job = str(context.workspace_id), str(context.job_id)
    with database.tenant(context.actor_id, workspace) as session:
        store.save(session, job, verified)

    def revoke():
        with database.tenant(context.actor_id, workspace) as session:
            grants.revoke(session, verified.report.grant_id)

    stub = SummaryStub(
        str(uuid5(NAMESPACE_URL, verified.report.response_sha256 + ":0")),
        verified.report.summary[0],
        hook=revoke,
    )
    with pytest.raises(AnalyticsUnavailable):
        await store.execute(database, context, model=LocalStructuredModel(model_instance=stub))
    with database.tenant(context.actor_id, workspace) as session:
        row = (
            session.execute(sa.select(summary_jobs).where(summary_jobs.c.id == job))
            .mappings()
            .one()
        )
        assert row["state"] == "cancelled" and row["ciphertext"] == b""
