"""Company/public/group scope must not be guessed from Facebook page access."""

from datetime import UTC, datetime

import pytest

from skriller.connectors.facebook_read import (
    FacebookRead,
    FacebookSearch,
    parse_profile_response,
    parse_search_response,
)

NOW = datetime(2026, 10, 17, tzinfo=UTC)


def test_display_counts_stay_text_and_profile_identity_is_unknown():
    output = parse_profile_response(
        [
            {
                "name": "Synthetic",
                "username": "synthetic",
                "friends": "-",
                "followers": "1.2K followers",
                "url": "https://www.facebook.com/synthetic",
            }
        ],
        FacebookRead(username="synthetic"),
        observed_at=NOW,
    )
    assert output.followers_display == "1.2K followers"
    assert output.friends_display is None
    assert output.visibility == "unknown" and output.company_identity == "unknown"
    assert output.subject_identity == "unknown" and output.group_access == "unavailable"
    assert output.coverage_complete is False


def test_group_reference_is_omitted_while_page_and_distinct_posts_remain():
    urls = [
        "https://www.facebook.com/groups/123/",
        "https://www.facebook.com/pages/synthetic/12",
        "https://www.facebook.com/story.php?story_fbid=1&id=9",
        "https://www.facebook.com/story.php?story_fbid=2&id=9",
        "https://www.facebook.com/synthetic",
    ]
    rows = [
        {"index": index, "title": "Synthetic", "text": "Fixture", "url": url}
        for index, url in enumerate(urls, 1)
    ]
    output = parse_search_response(rows, FacebookSearch(query="synthetic"), observed_at=NOW)
    assert output.omitted_unsupported == 1
    assert [row.resource_kind for row in output.references] == [
        "page_reference",
        "content_reference",
        "content_reference",
        "unknown",
    ]
    assert all(
        row.visibility == "unknown" and row.company_identity == "unknown"
        for row in output.references
    )
    assert len({row.source_url for row in output.references}) == 4


@pytest.mark.parametrize(
    "url",
    [
        "https://www.facebook.com.evil.example/page",
        "https://evil.example/page",
        "http://www.facebook.com/page",
        "https://user:password@www.facebook.com/page",
        "https://www.facebook.com/story.php?id=9",
        "https://www.facebook.com/story.php?story_fbid=1&id=9&ref=tracking",
        "https://www.facebook.com/story.php?story_fbid=1&story_fbid=2",
    ],
)
def test_untrusted_or_ambiguous_source_identity_is_rejected(url):
    with pytest.raises(ValueError):
        parse_search_response(
            [{"index": 1, "title": "Synthetic", "text": "", "url": url}],
            FacebookSearch(query="synthetic"),
            observed_at=NOW,
        )


@pytest.mark.parametrize("username", ["groups", "../other", "me", "profile.php", "login"])
def test_profile_request_is_explicit_and_cannot_target_a_group_or_account_route(username):
    with pytest.raises(ValueError):
        FacebookRead(username=username)


def test_typed_reference_cannot_bypass_group_scope_by_claiming_unknown_kind():
    from skriller.connectors.facebook_read import FacebookReference

    with pytest.raises(ValueError):
        FacebookReference(
            title="Synthetic",
            excerpt="",
            source_url="https://www.facebook.com/groups/123",
            observed_at=NOW,
            resource_kind="unknown",
        )
    with pytest.raises(ValueError):
        FacebookRead(username="logout.php")
