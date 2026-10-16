"""Owner metrics, partial failures and copied summary accounting on PostgreSQL."""

import json
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

import pytest
import sqlalchemy as sa
from langchain_core.messages import AIMessage
from test_saved_graph import context_for
from test_youtube_analytics import CHANNEL, Provider, app_for, consent

from skriller.analytics.google import AnalyticsUnavailable
from skriller.analytics.reports import ReportRequest, read_report
from skriller.analytics.router import configuration
from skriller.analytics.summaries import summarize_report
from skriller.analytics.tables import grants
from skriller.db import WorkspaceRepository
from skriller.extraction.models import LocalStructuredModel
from skriller.jobs.budget import current_usage

pytestmark = pytest.mark.integration_db
REQUEST = {
    "start_date": "2026-01-01",
    "end_date": "2026-01-02",
    "metrics": ["views", "estimatedMinutesWatched"],
}


class ReportsProvider(Provider):
    def __init__(self, *, report_hook=None, failure=None, malformed=False):
        super().__init__()
        self.report_hook, self.failure, self.malformed = report_hook, failure, malformed
        self.report_calls = 0

    def report(self, token, channel, start, end, metrics):
        self.report_calls += 1
        assert token in {"SENTINEL_ACCESS", "NEW_ACCESS"} and channel == CHANNEL
        assert start.isoformat() == REQUEST["start_date"] and end.isoformat() == REQUEST["end_date"]
        if self.report_hook:
            self.report_hook()
        if self.failure:
            raise AnalyticsUnavailable(self.failure)
        result = {
            "kind": "youtubeAnalytics#resultTable",
            "columnHeaders": [{"name": "day", "columnType": "DIMENSION", "dataType": "STRING"}]
            + [
                {
                    "name": metric,
                    "columnType": "METRIC",
                    "dataType": "INTEGER" if metric == "views" else "FLOAT",
                }
                for metric in metrics
            ],
            "rows": [["2026-01-01", *[120 if metric == "views" else 1.25 for metric in metrics]]],
        }
        if self.malformed:
            result["rows"][0][1] = "guess"
        return result


def connected(database, provider, **identity):
    actor, workspace, app, client, path = app_for(database, provider, **identity)
    body = consent(client, path)
    response = client.post(path + "/oauth/complete", json=body)
    assert response.status_code == 201, response.text
    return actor, workspace, app, client, path, body["grant_id"]


def test_owner_metrics_preserve_exact_values_citation_timezone_and_unknown_days(database):
    provider = ReportsProvider()
    _actor, _workspace, _app, client, path, identifier = connected(database, provider)
    response = client.post(
        path + f"/grants/{identifier}/reports",
        json={**REQUEST, "metrics": [*REQUEST["metrics"], "estimatedRevenue"]},
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["status"] == "partial"
    assert report["channel_id"] == CHANNEL
    assert report["rows"] == [
        {"day": "2026-01-01", "metrics": {"views": 120, "estimatedMinutesWatched": 1.25}}
    ]
    assert report["unavailable_metrics"] == {"estimatedRevenue": "unsupported_metric"}
    assert report["coverage_complete"] is False and report["timezone"] == "America/Los_Angeles"
    assert report["currency"] is None and len(report["response_sha256"]) == 64
    assert "SENTINEL" not in response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert report["summary"] == [
        "2026-01-01: views=120 count; estimatedMinutesWatched=1.25 minutes"
    ]
    assert provider.report_calls == 1
    unsupported = client.post(
        path + f"/grants/{identifier}/reports", json={**REQUEST, "metrics": ["estimatedRevenue"]}
    )
    assert unsupported.json()["status"] == "unavailable" and provider.report_calls == 1
    assert (
        client.post(
            path + f"/grants/{identifier}/reports", json={**REQUEST, "channel_id": "someone-else"}
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "failure,malformed,reason",
    [
        ("analytics_quota_exhausted", False, "analytics_quota_exhausted"),
        (None, True, "analytics_report_schema_invalid"),
        ("analytics_authorization_expired", False, "analytics_authorization_expired"),
    ],
)
def test_provider_failures_never_become_guessed_metrics(database, failure, malformed, reason):
    actor, workspace, app, client, path, identifier = connected(
        database, ReportsProvider(failure=failure, malformed=malformed)
    )
    response = client.post(path + f"/grants/{identifier}/reports", json=REQUEST)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["status"] == "unavailable" and report["rows"] == [] and report["summary"] == []
    assert set(report["unavailable_metrics"].values()) == {reason}
    with database.tenant(actor, workspace) as session:
        row = app.state.analytics_store.get(session, identifier)
        assert row["state"] == (
            "revoked" if failure == "analytics_authorization_expired" else "active"
        )


def test_access_expiry_refreshes_once_and_revoke_during_report_discards_output(database):
    provider = ReportsProvider()
    actor, workspace, app, client, path, identifier = connected(database, provider)
    with database.tenant(actor, workspace) as session:
        session.execute(
            sa.update(grants)
            .where(grants.c.id == identifier)
            .values(access_expires_at=sa.func.now() - timedelta(seconds=1))
        )
    assert client.post(path + f"/grants/{identifier}/reports", json=REQUEST).status_code == 200
    assert provider.calls == 2 and provider.report_calls == 1

    def revoke():
        with database.tenant(actor, workspace) as session:
            app.state.analytics_store.revoke(session, identifier)

    provider.report_hook = revoke
    late = client.post(path + f"/grants/{identifier}/reports", json=REQUEST)
    assert late.status_code == 409 and "120" not in late.text
    assert client.post(path + f"/grants/{identifier}/reports", json=REQUEST).status_code == 409
    assert provider.report_calls == 2


def test_other_owner_or_member_cannot_request_private_reports(database):
    from uuid import uuid4

    provider = ReportsProvider()
    actor, workspace, _app, client, path, identifier = connected(database, provider)
    other, member = "coowner-" + str(uuid4()), "member-" + str(uuid4())
    with database.tenant(actor, workspace) as session:
        WorkspaceRepository.add_member(session, other, role="owner")
        WorkspaceRepository.add_member(session, member)
    client.headers["Authorization"] = "Bearer " + other
    assert client.post(path + f"/grants/{identifier}/reports", json=REQUEST).status_code == 409
    client.headers["Authorization"] = "Bearer " + member
    assert client.post(path + f"/grants/{identifier}/reports", json=REQUEST).status_code == 403
    del client.headers["Authorization"]
    assert client.post(path + f"/grants/{identifier}/reports", json=REQUEST).status_code == 401
    assert provider.report_calls == 0


class SummaryStub:
    def __init__(self, identifier, quote, hook=None):
        self.identifier, self.quote, self.hook, self.calls = identifier, quote, hook, 0

    async def ainvoke(self, messages, config):
        self.calls += 1
        if self.hook:
            self.hook()
        return AIMessage(
            content=json.dumps({"evidence_ids": [self.identifier], "quotes": [self.quote]}),
            usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        )


@pytest.mark.parametrize("invalid_quote", [False, True])
async def test_private_summary_reuses_actual_copied_node_ledger_and_exact_quotes(
    database, invalid_quote
):
    context = context_for(database)
    actor, workspace, app, _client, _path, identifier = connected(
        database, ReportsProvider(), owner=context.actor_id, workspace=str(context.workspace_id)
    )
    config = configuration(type("Request", (), {"app": app})())
    verified = read_report(
        database,
        app.state.analytics_store,
        config,
        app.state.analytics_provider,
        actor,
        workspace,
        identifier,
        ReportRequest.model_validate(REQUEST),
    )
    evidence_id = str(uuid5(NAMESPACE_URL, verified.report.response_sha256 + ":0"))
    quote = "Revenue is high" if invalid_quote else verified.report.summary[0]
    stub = SummaryStub(evidence_id, quote)
    summary = await summarize_report(
        database,
        app.state.analytics_store,
        context,
        verified,
        operation_key="analytics-summary",
        model=LocalStructuredModel(model_instance=stub),
    )
    assert stub.calls == 1
    assert summary.status == ("unknown" if invalid_quote else "answered")
    if invalid_quote:
        assert summary.unknowns == ("citation_invalid",)
    else:
        assert summary.observations[0].quote == quote
        assert summary.observations[0].stored_content_sha256 == verified.report.response_sha256
    with database.tenant(actor, workspace) as session:
        assert current_usage(session, str(context.job_id))[1]["llm_calls"] == 1


async def test_summary_revoke_during_model_io_discards_private_answer(database):
    context = context_for(database)
    actor, workspace, app, _client, _path, identifier = connected(
        database, ReportsProvider(), owner=context.actor_id, workspace=str(context.workspace_id)
    )
    config = configuration(type("Request", (), {"app": app})())
    verified = read_report(
        database,
        app.state.analytics_store,
        config,
        app.state.analytics_provider,
        actor,
        workspace,
        identifier,
        ReportRequest.model_validate(REQUEST),
    )

    def revoke():
        with database.tenant(actor, workspace) as session:
            app.state.analytics_store.revoke(session, identifier)

    stub = SummaryStub(
        str(uuid5(NAMESPACE_URL, verified.report.response_sha256 + ":0")),
        verified.report.summary[0],
        hook=revoke,
    )
    with pytest.raises(AnalyticsUnavailable):
        await summarize_report(
            database,
            app.state.analytics_store,
            context,
            verified,
            operation_key="analytics-summary-revoke",
            model=LocalStructuredModel(model_instance=stub),
        )
    assert stub.calls == 1
