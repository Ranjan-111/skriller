"""Typed public YouTube metadata and supplied VTT transcript parsing.

The isolated yt-dlp command is defined in the reviewed runner. This module only
parses bounded output; it performs no HTTP calls or transcript generation.
"""

import json
import re
from datetime import UTC, date, datetime
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from agent_reach.utils.url import host_matches, normalize_public_http_url
from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAX_METADATA_BYTES = 1_048_576
MAX_TRANSCRIPT_BYTES = 1_048_576
MAX_SEGMENTS = 5000


class YouTubeUnavailable(ValueError):
    pass


class YouTubeVideoEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: Literal["youtube"] = "youtube"
    evidence_kind: Literal["public_video_metadata"] = "public_video_metadata"
    counter_scope: Literal["public_metadata"] = "public_metadata"
    source_url: str = Field(max_length=2048)
    observed_at: datetime
    published_on: date | None = None
    title: str = Field(min_length=1, max_length=500)
    channel: str | None = Field(default=None, max_length=300)
    channel_url: str | None = Field(default=None, max_length=2048)
    description: str | None = Field(default=None, max_length=8192)
    duration_seconds: int | None = Field(default=None, ge=0)
    view_count: int | None = Field(default=None, ge=0)
    like_count: int | None = Field(default=None, ge=0)
    transcript_state: Literal["available", "unavailable"]
    transcript_languages: tuple[str, ...] = Field(max_length=30)


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=8192)
    source_url: str = Field(max_length=2048)
    observed_at: datetime
    source: Literal["youtube_caption"] = "youtube_caption"


def _public_youtube_url(value: str) -> str:
    try:
        url = normalize_public_http_url(value)
    except (TypeError, ValueError) as exc:
        raise YouTubeUnavailable("Video URL is unavailable") from exc
    if not host_matches(url, "youtube.com", "youtu.be"):
        raise YouTubeUnavailable("Video URL is unavailable")
    return url


def _caption_languages(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, dict):
        return ()
    return tuple(sorted(key[:30] for key in raw if isinstance(key, str))[:30])


def _video_id(value: str) -> str | None:
    parsed = urlsplit(value)
    if parsed.hostname == "youtu.be":
        return parsed.path.strip("/").split("/", 1)[0] or None
    parts = [part for part in parsed.path.split("/") if part]
    if parts and parts[0] == "watch":
        values = parse_qs(parsed.query).get("v", [])
        return values[0] if values else None
    if len(parts) >= 2 and parts[0] in {"shorts", "live", "embed"}:
        return parts[1]
    return None


def parse_metadata_output(
    output: str | bytes, *, requested_url: str, observed_at: datetime | None = None
) -> YouTubeVideoEvidence:
    if isinstance(output, str):
        encoded = output.encode("utf-8")
    elif isinstance(output, bytes):
        encoded = output
    else:
        raise TypeError("yt-dlp output must be text or bytes")
    if len(encoded) > MAX_METADATA_BYTES:
        raise YouTubeUnavailable("Video metadata exceeds its output limit")
    try:
        raw = json.loads(encoded)
    except (ValueError, UnicodeDecodeError) as exc:
        raise YouTubeUnavailable("Video metadata is invalid") from exc
    if not isinstance(raw, dict):
        raise YouTubeUnavailable("Video metadata is invalid")
    requested = _public_youtube_url(requested_url)
    source_url = _public_youtube_url(raw.get("webpage_url") or requested)
    if not _video_id(requested) or _video_id(source_url) != _video_id(requested):
        raise YouTubeUnavailable("Video metadata did not match the requested source")
    upload = raw.get("upload_date")
    try:
        published = datetime.strptime(upload, "%Y%m%d").date() if upload else None
    except (TypeError, ValueError):
        published = None
    captions = raw.get("subtitles")
    automatic = raw.get("automatic_captions")
    languages = tuple(sorted(set(_caption_languages(captions) + _caption_languages(automatic))))
    raw_channel_url = raw.get("channel_url") or raw.get("uploader_url")
    channel_url = _public_youtube_url(raw_channel_url) if raw_channel_url else None
    data = {
        "source_url": source_url,
        "observed_at": observed_at or datetime.now(UTC),
        "published_on": published,
        "title": raw.get("title"),
        "channel": raw.get("channel") or raw.get("uploader"),
        "channel_url": channel_url,
        "description": raw.get("description"),
        "duration_seconds": raw.get("duration"),
        "view_count": raw.get("view_count"),
        "like_count": raw.get("like_count"),
        "transcript_state": "available" if languages else "unavailable",
        "transcript_languages": languages,
    }
    try:
        return YouTubeVideoEvidence.model_validate(data)
    except ValidationError as exc:
        raise YouTubeUnavailable("Video metadata did not match the reviewed schema") from exc


_TIME = re.compile(r"(?:(\d{1,}):)?(\d{2}):(\d{2})[.,](\d{3})")


def _seconds(value: str) -> float:
    match = _TIME.fullmatch(value.strip())
    if not match:
        raise ValueError("Invalid WebVTT timestamp")
    hours, minutes, seconds, millis = match.groups()
    total = int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000
    return float(total)


def parse_webvtt(
    content: str | bytes,
    *,
    source_url: str,
    observed_at: datetime | None = None,
) -> tuple[TranscriptSegment, ...]:
    """Parse provided WebVTT cues with timestamps; never synthesize missing text."""
    if isinstance(content, str):
        raw = content.encode("utf-8")
    elif isinstance(content, bytes):
        raw = content
    else:
        raise TypeError("Transcript must be supplied WebVTT text or bytes")
    if len(raw) > MAX_TRANSCRIPT_BYTES:
        raise YouTubeUnavailable("Transcript exceeds its size limit")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise YouTubeUnavailable("Transcript encoding is invalid") from exc
    if not text.startswith("WEBVTT"):
        raise YouTubeUnavailable("Transcript format is unavailable")
    source = _public_youtube_url(source_url)
    if not _video_id(source):
        raise YouTubeUnavailable("Transcript source must identify a public video")
    collected_at = observed_at or datetime.now(UTC)
    segments = []
    for block in re.split(r"\n\s*\n", text)[1:]:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing = next((line for line in lines if "-->" in line), None)
        if timing is None:
            continue
        start, _, end = timing.partition("-->")
        end = end.split(maxsplit=1)[0]
        start_seconds, end_seconds = _seconds(start), _seconds(end)
        cue = " ".join(
            line for line in lines[lines.index(timing) + 1 :] if not line.startswith("<")
        ).strip()
        cue = re.sub(r"<[^>]{1,100}>", "", cue)
        if not cue or end_seconds <= start_seconds:
            continue
        segments.append(
            TranscriptSegment(
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                text=cue,
                source_url=source,
                observed_at=collected_at,
            )
        )
        if len(segments) >= MAX_SEGMENTS:
            break
    return tuple(segments)
