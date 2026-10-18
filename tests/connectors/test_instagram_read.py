"""Public scope and uncertainty at the copied read/output boundary."""

from datetime import UTC, datetime

import pytest

from skriller.connectors.instagram_read import (
    InstagramRead,
    InstagramSearch,
    parse_profile_response,
    parse_search_response,
)

NOW = datetime(2026, 10, 17, tzinfo=UTC)


def row():
    return {
        "username": "synthetic",
        "name": "Synthetic Account",
        "bio": "Synthetic excerpt",
        "private": False,
        "verified": None,
        "followers": None,
        "following": 0,
        "posts": 12,
        "avatar_url": "https://cdn.example/temporary-signed-avatar",
    }


def test_public_profile_preserves_null_counts_without_claiming_owner_analytics():
    profile = parse_profile_response([row()], InstagramRead(username="synthetic"), observed_at=NOW)
    assert profile.followers is None and profile.following == 0 and profile.posts == 12
    assert profile.verified is None
    assert profile.visibility == "public"
    assert profile.owner_analytics == "unavailable"
    assert profile.account_kind == "unknown" and profile.subject_identity == "unknown"
    assert profile.coverage_complete is False
    assert "avatar" not in profile.model_dump_json()


@pytest.mark.parametrize(
    "patch",
    [
        {"private": True},
        {"private": None},
        {"private": 0},
        {"username": "another"},
        {"followers": True},
        {"followers": -1},
        {"followers": "1.2K"},
        {"verified": "No"},
        {"cookie": "synthetic-unwanted-field"},
    ],
)
def test_private_mismatched_or_misleading_profile_output_is_rejected(patch):
    with pytest.raises(ValueError):
        parse_profile_response(
            [{**row(), **patch}], InstagramRead(username="synthetic"), observed_at=NOW
        )


@pytest.mark.parametrize("username", ["../accounts", "accounts", "@name", "a/b", "", "a" * 31])
def test_request_rejects_paths_reserved_routes_and_invalid_handles(username):
    with pytest.raises(ValueError):
        InstagramRead(username=username)


def test_profile_observation_requires_an_aware_time():
    with pytest.raises(ValueError):
        parse_profile_response(
            [row()], InstagramRead(username="synthetic"), observed_at=datetime(2026, 10, 17)
        )


def test_search_deduplicates_public_references_and_drops_avatar_transport_data():
    reference = {
        key: value
        for key, value in row().items()
        if key in {"username", "name", "private", "verified", "avatar_url"}
    }
    reference["url"] = "https://www.instagram.com/synthetic"
    parsed = parse_search_response(
        [reference, reference], InstagramSearch(query="synthetic", limit=2), observed_at=NOW
    )
    assert len(parsed) == 1
    assert parsed[0].source_url == "https://www.instagram.com/synthetic/"
    assert "avatar" not in parsed[0].model_dump_json()
    for patch in [{"private": "No"}, {"private": None}, {"url": "https://evil.example/synthetic"}]:
        with pytest.raises(ValueError):
            parse_search_response(
                [{**reference, **patch}], InstagramSearch(query="synthetic"), observed_at=NOW
            )
