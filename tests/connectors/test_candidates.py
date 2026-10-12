import pytest

from skriller.connectors.candidates import canonical_url, deduplicate
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
