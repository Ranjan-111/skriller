import pytest

from skriller.connectors.rss import MAX_FEED_BYTES, parse_feed


def test_rss_keeps_source_date_attribution_and_deduplicates_items():
    body = b'''<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Example</title>
      <item><guid>story-1</guid><title>Hiring update</title>
        <link>/posts/one</link><pubDate>Mon, 12 Oct 2026 09:30:00 GMT</pubDate>
        <description><![CDATA[Hiring software engineers.]]></description></item>
      <item><guid>story-2</guid><title>Duplicate URL</title>
        <link>https://news.example.com/posts/one</link>
        <pubDate>Tue, 13 Oct 2026 09:30:00 GMT</pubDate></item>
    </channel></rss>'''
    result = parse_feed(body, "https://news.example.com/feeds/main")
    assert len(result.entries) == 1
    entry = result.entries[0]
    assert entry.entry_id == "story-1"
    assert entry.url == "https://news.example.com/posts/one"
    assert entry.feed_url == result.feed_url == "https://news.example.com/feeds/main"
    assert entry.published_at == "2026-10-12T09:30:00+00:00"
    assert entry.summary == "Hiring software engineers."
    assert entry.source == "rss"
    assert result.duplicate_count == 1


def test_atom_relative_links_keep_published_date_and_missing_dates_stay_missing():
    body = b'''<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><id>tag:example.com,2026:1</id><title>Published</title>
        <link href="/entry/1"/><published>2026-10-12T11:00:00Z</published>
        <summary>Public statement</summary></entry>
      <entry><id>tag:example.com,2026:2</id><title>No date</title>
        <link href="entry/2"/></entry>
    </feed>'''
    result = parse_feed(body, "https://news.example.com/atom/feed")
    assert result.malformed is False
    assert len(result.entries) == 2
    assert result.entries[0].url == "https://news.example.com/entry/1"
    assert result.entries[0].published_at == "2026-10-12T11:00:00+00:00"
    assert result.entries[1].url == "https://news.example.com/atom/entry/2"
    assert result.entries[1].published_at is None


def test_private_entry_links_are_omitted_and_oversized_summaries_are_labelled():
    body = ('''<rss><channel>
      <item><guid>private</guid><title>Local target</title>
        <link>http://127.0.0.1/admin</link></item>
      <item><guid>large</guid><title>Long content</title>
        <link>https://news.example.com/long</link><description>'''
        + "x" * 9000
        + "</description></item></channel></rss>").encode()
    result = parse_feed(body, "https://news.example.com/feed")
    assert result.invalid_link_count == 1
    assert len(result.entries) == 1
    assert len(result.entries[0].summary) == 8192
    assert result.entries[0].summary_truncated is True
    assert result.truncated_entry_count == 1


def test_feed_parser_bounds_inputs_and_never_fetches_source_urls():
    with pytest.raises(ValueError, match="2 MiB"):
        parse_feed(b"x" * (MAX_FEED_BYTES + 1), "https://news.example.com/feed")
    with pytest.raises(ValueError, match="between 1 and 100"):
        parse_feed(b"<rss/>", "https://news.example.com/feed", max_entries=101)
    with pytest.raises(ValueError):
        parse_feed(b"<rss/>", "http://169.254.169.254/latest/meta-data")
    with pytest.raises(TypeError, match="bytes"):
        parse_feed("https://news.example.com/feed", "https://news.example.com/feed")
