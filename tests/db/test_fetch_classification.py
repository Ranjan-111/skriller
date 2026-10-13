import json
from uuid import uuid4

import pytest
from test_fetch import ctx
from test_fetch import proxy as _proxy

from skriller.connectors.fetch import FetchUnavailable, HTTPFetcher
from skriller.jobs.budget import current_usage
from skriller.storage import EvidenceStorage, LocalBlobBackend

proxy = _proxy
pytestmark = pytest.mark.integration_db


@pytest.mark.parametrize(
    "path,status,next_method",
    [
        ("/login200", "auth_required", "connection"),
        ("/dynamic", "js_shell", "dynamic"),
        ("/challenge", "challenge", "stop"),
    ],
)
def test_http200_blocked_and_unrendered_body_never_becomes_read_artifact(
    database, proxy, path, status, next_method, tmp_path
):
    endpoint, requests, _ = proxy
    context = ctx(database)
    with pytest.raises(FetchUnavailable) as failure:
        HTTPFetcher(database, trusted_proxy_url=endpoint).fetch(
            context, "http://example.com" + path, source="web", operation_key=uuid4().hex
        )
    classification = failure.value.classification
    assert classification.status == status and classification.next_method == next_method
    assert classification.evidence_kind == "none"
    assert requests == [path]  # no automatic browser/solver/retry follows classification
    assert not list(tmp_path.rglob("evidence/*"))
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        assert current_usage(session, str(context.job_id))[1]["fetch_attempts"] == 1


def test_explicit_empty_results_store_only_empty_state_evidence(database, proxy, tmp_path):
    endpoint, requests, _ = proxy
    context = ctx(database)
    artifact = HTTPFetcher(database, trusted_proxy_url=endpoint).fetch(
        context, "http://example.com/empty-results", source="web", operation_key=uuid4().hex
    )
    assert artifact.classification.status == "empty_results"
    assert (
        artifact.classification.next_method == "stop" and artifact.evidence_kind == "empty_results"
    )
    storage = EvidenceStorage(LocalBlobBackend(tmp_path))
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        record = artifact.persist(session, storage)
        metadata = json.loads(storage.retrieve(session, record["metadata_evidence_id"]))
        assert metadata["classification"] == "empty_results" and metadata["next_method"] == "stop"
        assert metadata["evidence_kind"] == "empty_results"
    assert requests == ["/empty-results"]
