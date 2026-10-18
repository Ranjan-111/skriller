"""Registered source discovery through real tenant checkpoints; browser IO is controlled."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from test_research_workflow import Provider, isolate_capacity, prepare

from skriller.connections.keys import Keyring
from skriller.connections.store import ConnectionStore, SecretPayload
from skriller.connectors.facebook_read import FacebookSearch
from skriller.connectors.facebook_read import parse_search_response as facebook_search
from skriller.connectors.instagram_read import InstagramSearch
from skriller.connectors.instagram_read import parse_search_response as instagram_search
from skriller.connectors.social_executor import ConcreteSocialExecutor
from skriller.jobs.worker import CheckpointWorker
from skriller.research.service import execute_discovery
from skriller.security.runner import RunResult
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db


class Runner:
    def __init__(self, source, failed, profile_link=False):
        self.source, self.failed = source, failed
        self.calls = 0
        self.profile_link = profile_link

    def run(self, operation, target, **kwargs):
        assert operation == self.source + "_search"
        assert kwargs["cancel_check"]() is False
        self.calls += 1
        if self.failed:
            return RunResult("completed", 0, '{"_skriller_error":"auth_expired"}', "", 1)
        now = datetime.now(UTC)
        if self.source == "instagram":
            request = InstagramSearch.model_validate_json(target)
            rows = instagram_search(
                [
                    {
                        "rank": 1,
                        "username": "synthetic",
                        "name": "Synthetic public account",
                        "verified": None,
                        "private": False,
                        "url": "https://www.instagram.com/synthetic",
                        "avatar_url": "",
                    }
                ],
                request,
                observed_at=now,
            )
            data = [row.model_dump(mode="json") for row in rows]
        else:
            request = FacebookSearch.model_validate_json(target)
            data = facebook_search(
                [
                    {
                        "index": 1,
                        "title": "Synthetic page",
                        "text": "Displayed company page reference",
                        "url": "https://www.facebook.com/synthetic"
                        if self.profile_link
                        else "https://www.facebook.com/pages/synthetic/123",
                    },
                    {
                        "index": 2,
                        "title": "Unsupported group",
                        "text": "Group reference omitted",
                        "url": "https://www.facebook.com/groups/456",
                    },
                ],
                request,
                observed_at=now,
            ).model_dump(mode="json")
        return RunResult(
            "completed",
            0,
            json.dumps(
                {
                    "data": data,
                    "network_requests_seen": 5,
                    "api_requests": 1 if self.source == "instagram" else 0,
                }
            ),
            "",
            1,
        )


@pytest.mark.parametrize("source", ["instagram", "facebook"])
@pytest.mark.parametrize("failed", [False, True])
def test_durable_discovery_keeps_other_sources_and_never_replays_or_silently_falls_back(
    database, monkeypatch, source, failed
):
    actor = "social-discover-" + uuid4().hex
    _, client, accepted = prepare(
        database, monkeypatch, actor, sources=[source, "web"], settings=Settings()
    )
    store = ConnectionStore(Keyring("fixture", {"fixture": b"a" * 32}))
    credentials = {"session_cookie": "synthetic-session"}
    if source == "facebook":
        credentials["user_id"] = "12345"
    with database.tenant(actor, accepted["workspace_id"]) as session:
        store.create(
            session,
            source,
            "session",
            SecretPayload(credentials=credentials),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes=("read", "discover"),
        )
    reader = ConcreteSocialExecutor(source, "sha256:" + "a" * 64)
    reader.runner = Runner(source, failed)
    isolate_capacity(monkeypatch, accepted["job_id"])
    payload = {
        "actor_id": actor,
        "workspace_id": accepted["workspace_id"],
        "job_id": accepted["job_id"],
    }
    payload["attempt_id"] = CheckpointWorker(database, {}).schedule(payload)["attempt_id"]
    provider = Provider()
    options = {source + "_reader": reader, "connection_store": store}
    outcome = execute_discovery(database, payload, provider, **options)
    assert outcome["status"] == "checkpointed", outcome
    execute_discovery(database, payload, provider, **options)
    assert reader.runner.calls == 1 and provider.calls == 1
    response = client.get(
        f"/v1/jobs/{accepted['job_id']}/results?workspace_id={accepted['workspace_id']}"
    )
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert len(results) == (1 if failed else 2)
    assert any(row["source"] == "web" for row in results)
    if not failed:
        row = next(row for row in results if row["source"] == source)
        assert row["provider"] == "opencli_" + source
        assert row["evidence_kind"] == "search_reference" and row["qualification"] == "unverified"
        assert row["platform_reference"]["access"] == "connected_search_reference_only"
        assert row["platform_reference"]["direct_read_status"] == "not_attempted"
        assert row["platform_reference"]["subject_identity"] == "unknown"
        assert row["provenance"][0]["provider"] == "opencli_" + source
        assert "groups/456" not in response.text
