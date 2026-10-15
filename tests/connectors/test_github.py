"""GitHub connector contracts run against synthetic public API responses."""

from datetime import UTC, datetime

import httpx
import pytest
from github_fixtures import repo_payload

from skriller.connectors.github import GitHubPublicReader, GitHubUnavailable


@pytest.mark.asyncio
async def test_repository_returns_dated_public_metadata_and_uses_only_read_api():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=repo_payload())

    reader = GitHubPublicReader(transport=httpx.MockTransport(respond))
    evidence = await reader.repository("https://github.com/acme/demo")

    assert evidence.source == "github"
    assert evidence.evidence_kind == "public_api_metadata"
    assert evidence.access_scope == "public_only"
    assert evidence.record.updated_at == datetime(2025, 1, 1, tzinfo=UTC)
    assert evidence.source_url == "https://github.com/acme/demo"
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url == "https://api.github.com/repos/acme/demo"
    assert "authorization" not in requests[0].headers


@pytest.mark.asyncio
async def test_public_profile_preserves_only_explicitly_published_fields():
    payload = {
        "id": 42,
        "login": "acme",
        "type": "Organization",
        "html_url": "https://github.com/acme",
        "name": "Acme Labs",
        "company": None,
        "bio": "Public profile",
        "location": "Bengaluru",
        "blog": "https://acme.example/",
        "public_repos": 4,
        "followers": 3,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "email": "private@example.com",
    }
    reader = GitHubPublicReader(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )
    evidence = await reader.profile("acme")

    assert evidence.record.name == "Acme Labs"
    assert evidence.record.bio == "Public profile"
    assert "email" not in evidence.record.model_dump()


@pytest.mark.asyncio
async def test_private_or_missing_repository_is_unavailable_and_writes_are_not_allowlisted():
    reader = GitHubPublicReader(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(404, json={"message": "Not Found"})
        )
    )
    with pytest.raises(GitHubUnavailable) as missing:
        await reader.repository("https://github.com/acme/private")
    assert missing.value.code == "not_found"
    with pytest.raises(ValueError, match="allowlisted"):
        await reader._get("/repos/acme/demo/issues")


@pytest.mark.asyncio
async def test_rate_limit_and_invalid_upstream_schema_are_typed_failures():
    limited = GitHubPublicReader(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(403, headers={"X-RateLimit-Remaining": "0"})
        )
    )
    with pytest.raises(GitHubUnavailable) as caught:
        await limited.profile("acme")
    assert caught.value.code == "rate_limited"

    malformed = GitHubPublicReader(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"[]"))
    )
    with pytest.raises(GitHubUnavailable) as caught:
        await malformed.repository("https://github.com/acme/demo")
    assert caught.value.code == "source_unavailable"


def test_repo_url_rejects_other_hosts_and_paths():
    for url in (
        "https://evil.example/acme/demo",
        "https://github.com/acme/demo/issues",
        "https://github.com/acme/%2e%2e",
    ):
        with pytest.raises(ValueError):
            # Validation is synchronous and does not issue a request.
            from skriller.connectors.github import _repo_path

            _repo_path(url)


@pytest.mark.asyncio
async def test_redirects_and_oversized_payloads_are_not_followed_or_parsed():
    calls = []

    def redirect(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://evil.example/collect"})

    reader = GitHubPublicReader(transport=httpx.MockTransport(redirect))
    with pytest.raises(GitHubUnavailable) as caught:
        await reader.profile("acme")
    assert caught.value.code == "source_unavailable"
    assert len(calls) == 1

    huge = GitHubPublicReader(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"{" + b" " * 256_000 + b"}")
        )
    )
    with pytest.raises(GitHubUnavailable) as caught:
        await huge.profile("acme")
    assert caught.value.code == "source_unavailable"


@pytest.mark.asyncio
async def test_upstream_html_url_must_match_expected_public_github_record():
    reader = GitHubPublicReader(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=repo_payload(html_url="https://attacker.example/acme/demo"),
            )
        )
    )
    with pytest.raises(GitHubUnavailable) as caught:
        await reader.repository("https://github.com/acme/demo")
    assert caught.value.code == "source_unavailable"


@pytest.mark.asyncio
async def test_private_visibility_is_never_returned_as_a_public_record():
    reader = GitHubPublicReader(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=repo_payload(visibility="private"))
        )
    )
    with pytest.raises(GitHubUnavailable) as caught:
        await reader.repository("https://github.com/acme/demo")
    assert caught.value.code == "not_found"


@pytest.mark.asyncio
async def test_wrong_profile_subject_and_non_numeric_ids_are_rejected():
    reader = GitHubPublicReader(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=repo_payload(id=True)))
    )
    with pytest.raises(GitHubUnavailable):
        await reader.repository("https://github.com/acme/demo")
    profile = {
        "id": 42,
        "login": "someoneelse",
        "type": "User",
        "html_url": "https://github.com/someoneelse",
        "public_repos": 1,
        "followers": 1,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    reader = GitHubPublicReader(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=profile))
    )
    with pytest.raises(GitHubUnavailable):
        await reader.profile("acme")


@pytest.mark.asyncio
async def test_retry_after_from_copied_parser_is_preserved_without_retry():
    calls = []

    def reply(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})

    reader = GitHubPublicReader(transport=httpx.MockTransport(reply))
    with pytest.raises(GitHubUnavailable) as caught:
        await reader.profile("acme")
    assert len(calls) == 1 and caught.value.retry_after_seconds == 120


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://task:" + "a" * 43 + "@127.0.0.1:18080",
        "http://task:" + "a" * 43 + "@[::1]:18080",
    ],
)
def test_task_gateway_credentials_are_confined_to_loopback(endpoint):
    assert GitHubPublicReader(trusted_proxy_url=endpoint)._proxy == endpoint


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://user:password@127.0.0.1:18080",
        "http://task:short@127.0.0.1:18080",
        "http://task:" + "a" * 43 + "@egress-proxy:8080",
        "http://task:" + "a" * 43 + "@example.com:8080",
        "https://task:" + "a" * 43 + "@127.0.0.1:18080",
    ],
)
def test_invalid_or_remote_authenticated_gateway_is_rejected(endpoint):
    with pytest.raises(ValueError):
        GitHubPublicReader(trusted_proxy_url=endpoint)
