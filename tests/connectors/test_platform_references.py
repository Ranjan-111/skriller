import pytest

from skriller.connectors.platform_references import (
    PlatformReference,
    connected_linkedin_reference,
    indexed_platform_reference,
)


@pytest.mark.parametrize(
    "url,source,kind",
    [
        ("https://www.linkedin.com/in/example-founder/", "linkedin", "profile"),
        ("https://linkedin.com/company/example/", "linkedin", "company"),
        ("https://linkedin.com/feed/update/urn:li:activity:12345/", "linkedin", "post"),
        ("https://linkedin.com/search/results/people/", "linkedin", "unknown"),
        ("https://reddit.com/r/startups/", "reddit", "community"),
        ("https://reddit.com/user/example/", "reddit", "profile"),
        ("https://reddit.com/r/startups/comments/abc123/example/", "reddit", "post"),
        ("https://reddit.com/r/startups/comments/abc123/example/def456/", "reddit", "comment"),
        ("https://redd.it/abc123", "reddit", "post"),
    ],
)
def test_reference_routes_never_claim_direct_access_or_verified_subject(url, source, kind):
    assert indexed_platform_reference(url) == {
        "source": source,
        "resource_kind": kind,
        "discovery_backend": "exa_keyless",
        "access": "indexed_reference_only",
        "direct_read_status": "not_attempted",
        "subject_identity": "unknown",
    }


@pytest.mark.parametrize(
    "url",
    [
        "https://linkedin.com.evil.example/in/person",
        "https://evilreddit.com/r/test",
        "https://example.org",
    ],
)
def test_unrelated_or_lookalike_hosts_are_not_platform_references(url):
    assert indexed_platform_reference(url) is None


def test_connected_search_keeps_profile_access_and_identity_unknown():
    reference = connected_linkedin_reference("https://www.linkedin.com/in/example/")
    assert reference["discovery_backend"] == "linkedin_mcp"
    assert reference["access"] == "connected_search_reference_only"
    assert (
        reference["direct_read_status"] == "not_attempted"
        and reference["subject_identity"] == "unknown"
    )
    assert connected_linkedin_reference("https://reddit.com/r/startups/") is None


@pytest.mark.parametrize(
    "change",
    [
        {"source": "reddit"},
        {"access": "indexed_reference_only"},
        {"discovery_backend": "exa_keyless"},
    ],
)
def test_reference_origin_access_and_source_cannot_be_mixed(change):
    reference = connected_linkedin_reference("https://www.linkedin.com/in/example/")
    with pytest.raises(ValueError):
        PlatformReference.model_validate({**reference, **change})
