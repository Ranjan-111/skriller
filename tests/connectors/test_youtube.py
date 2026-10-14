import json
from datetime import UTC, date, datetime

import pytest

from skriller.connectors.youtube import (
    YouTubeUnavailable,
    parse_metadata_output,
    parse_webvtt,
)


def metadata(**changes):
    value = {
        "id": "fixture123",
        "webpage_url": "https://www.youtube.com/watch?v=fixture123",
        "title": "A public creator interview",
        "channel": "Example Creator",
        "channel_url": "https://www.youtube.com/@example",
        "upload_date": "20250102",
        "duration": 42,
        "view_count": 1200,
        "like_count": 30,
        "description": "Public video description",
        "subtitles": {},
        "automatic_captions": {},
    }
    value.update(changes)
    return value


def test_public_metadata_and_absent_captions_keep_clear_missing_state():
    evidence = parse_metadata_output(
        json.dumps(metadata()),
        requested_url="https://youtu.be/fixture123",
        observed_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    assert evidence.counter_scope == "public_metadata"
    assert evidence.view_count == 1200 and evidence.like_count == 30
    assert evidence.published_on == date(2025, 1, 2)
    assert evidence.observed_at == datetime(2026, 10, 1, tzinfo=UTC)
    assert evidence.transcript_state == "unavailable"
    assert evidence.transcript_languages == ()


def test_caption_availability_does_not_claim_a_transcript_was_extracted():
    evidence = parse_metadata_output(
        json.dumps(metadata(subtitles={"en": [{}]}, automatic_captions={"hi": [{}]})),
        requested_url="https://www.youtube.com/watch?v=fixture123",
    )
    assert evidence.transcript_state == "available"
    assert evidence.transcript_languages == ("en", "hi")
    assert not hasattr(evidence, "transcript")


def test_webvtt_segments_keep_source_timestamps():
    observed = datetime(2026, 10, 1, tzinfo=UTC)
    segments = parse_webvtt(
        "WEBVTT\n\n1\n00:00:01.250 --> 00:00:02.500 align:start\n"
        "We are hiring engineers.\n\n2\n1:02:03.000 --> 1:02:04.000\n"
        "Revenue is growing.\n",
        source_url="https://youtube.com/watch?v=fixture123",
        observed_at=observed,
    )
    assert all(item.source_url == "https://youtube.com/watch?v=fixture123" for item in segments)
    assert all(item.observed_at == observed for item in segments)
    assert [(item.start_seconds, item.end_seconds, item.text) for item in segments] == [
        (1.25, 2.5, "We are hiring engineers."),
        (3723.0, 3724.0, "Revenue is growing."),
    ]


def test_invalid_or_mismatched_video_output_is_not_attributed_to_requested_video():
    with pytest.raises(YouTubeUnavailable):
        parse_metadata_output(
            json.dumps(metadata(id="other", webpage_url="https://youtube.com/watch?v=other")),
            requested_url="https://youtube.com/watch?v=fixture123",
        )
    with pytest.raises(YouTubeUnavailable):
        parse_metadata_output("[]", requested_url="https://youtube.com/watch?v=fixture123")
    with pytest.raises(YouTubeUnavailable):
        parse_metadata_output(
            json.dumps(metadata()), requested_url="https://evil.example/watch?v=fixture123"
        )


def test_transcript_parser_requires_supplied_vtt_and_bounds_input():
    with pytest.raises(YouTubeUnavailable, match="format"):
        parse_webvtt("not captions", source_url="https://youtube.com/watch?v=fixture123")
    with pytest.raises(YouTubeUnavailable, match="size"):
        parse_webvtt(
            b"WEBVTT" + b" " * 1_048_576,
            source_url="https://youtube.com/watch?v=fixture123",
        )
