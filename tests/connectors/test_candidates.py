import pytest

from skriller.connectors.candidates import canonical_url, deduplicate, native_reference
from skriller.connectors.search import SearchHit, SearchPage


def page(url, query="founders"):
    return SearchPage(
        hits=[SearchHit(title="Same name", url=url, snippet="Reference", rank=1)],
        rejected=0,
        truncated=False,
        query=query,
    )


def test_tracking_variants_keep_original_query_provenance():
    first = "https://www.linkedin.com/in/ada?utm_source=search&trk=public"
    second = "https://www.linkedin.com/in/ada?trackingId=123"
    candidates = deduplicate([("linkedin", page(first)), ("web", page(second, "engineers"))])
    assert len(candidates) == 1
    assert candidates[0].canonical_url == "https://www.linkedin.com/in/ada"
    assert [item["original_url"] for item in candidates[0].provenance] == [first, second]
    assert len(candidates[0].identity_hash) == 64


def test_similar_names_native_ids_queries_and_fragments_are_not_merged():
    urls = [
        "https://example.com/user?id=1",
        "https://example.com/user?id=2",
        "https://example.com/user?id=1#person",
        "https://example.com/user?id=1#company",
    ]
    assert len(deduplicate([("web", page(url)) for url in urls])) == 4
    assert canonical_url("https://example.com/?ref=account&key=a%2Bb&key=c") == (
        "https://example.com/?ref=account&key=a%2Bb&key=c"
    )


def test_known_tracking_only_and_copied_guard():
    assert canonical_url("HTTPS://Example.com:443/?%75tm_source=x&id=1&fbclid=2") == (
        "https://example.com/?id=1"
    )
    assert canonical_url("https://notlinkedin.com/?trk=native") == (
        "https://notlinkedin.com/?trk=native"
    )
    for value in ["http://127.0.0.1/a", "https://user:secret@example.com/", "javascript:x"]:
        with pytest.raises(ValueError):
            canonical_url(value)


def test_bounded_selection_keeps_provenance_for_retained_identity():
    candidates = deduplicate(
        [
            ("web", page("https://example.com/one")),
            ("web", page("https://example.com/two")),
            ("linkedin", page("https://example.com/one?utm_source=a")),
        ],
        limit=1,
    )
    assert len(candidates) == 1 and len(candidates[0].provenance) == 2
    with pytest.raises(ValueError):
        deduplicate([], limit=0)


def test_reddit_native_post_aliases_deduplicate_but_comments_stay_distinct():
    urls = [
        "https://www.reddit.com/r/python/comments/abc123/first_title/",
        "https://old.reddit.com/r/python/comments/abc123/changed_title/",
        "https://redd.it/abc123",
        "https://reddit.com/r/python/comments/abc123/title/def456/",
        "https://reddit.com/r/python/comments/abc123/title/ghi789/",
    ]
    candidates = deduplicate([("reddit", page(url)) for url in urls])
    assert len(candidates) == 3
    assert candidates[0].native_id == {"namespace": "reddit_post", "id": "abc123"}
    assert len(candidates[0].provenance) == 3
    assert candidates[1].native_id == {"namespace": "reddit_comment", "id": "def456"}
    assert candidates[1].identity_hash != candidates[0].identity_hash


def test_linkedin_activity_aliases_do_not_merge_vanity_profiles_or_ugc_posts():
    urls = [
        "https://www.linkedin.com/posts/synthetic-activity-123456789-example",
        "https://linkedin.com/feed/update/urn:li:activity:123456789/",
        "https://linkedin.com/feed/update/urn:li:ugcPost:123456789/",
        "https://www.linkedin.com/in/synthetic",
        "https://www.linkedin.com/in/synthetic-other",
    ]
    candidates = deduplicate([("linkedin", page(url)) for url in urls])
    assert len(candidates) == 4
    assert candidates[0].native_id == {"namespace": "linkedin_activity", "id": "123456789"}
    assert len(candidates[0].provenance) == 2
    assert candidates[1].native_id["namespace"] == "linkedin_ugc_post"
    assert candidates[2].native_id is None


@pytest.mark.parametrize(
    "url",
    [
        "https://notreddit.com/comments/abc123/",
        "https://www.reddit.com/user/same_name/",
        "https://www.reddit.com/r/python/comments/abc123/title/?context=1",
        "https://www.reddit.com/r/python/comments/abc123/title/#comment",
        "https://www.reddit.com/r/python/comments/abc123/title/def456/extra/",
        "https://www.linkedin.com/posts/synthetic-activity-not_numeric-example",
        "https://www.linkedin.com/in/ada",
        "https://notlinkedin.com/feed/update/urn:li:activity:123/",
    ],
)
def test_uncertain_permalink_shapes_keep_plain_url_identity(url):
    assert native_reference(url) is None


def test_native_reference_reuses_public_url_security_guard():
    for url in [
        "https://user:secret@reddit.com/comments/abc123/",
        "http://127.0.0.1/comments/abc123/",
        "javascript:comments/abc123",
    ]:
        with pytest.raises(ValueError):
            native_reference(url)
