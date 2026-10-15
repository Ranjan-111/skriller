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
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

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
    observed_at: AwareDatetime
    published_on: date | None = None
    title: str = Field(min_length=1, max_length=500)
    channel: str | None = Field(default=None, max_length=300)
    channel_url: str | None = Field(default=None, max_length=2048)
    description: str | None = Field(default=None, max_length=8192)
    duration_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    view_count: int | None = Field(default=None, ge=0, strict=True)
    like_count: int | None = Field(default=None, ge=0, strict=True)
    transcript_state: Literal["available", "unavailable"]
    transcript_languages: tuple[str, ...] = Field(max_length=30)


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, allow_inf_nan=False)
    text: str = Field(min_length=1, max_length=8192)
    source_url: str = Field(max_length=2048)
    observed_at: AwareDatetime
    source: Literal["youtube_caption"] = "youtube_caption"


class YouTubeReadEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    metadata: YouTubeVideoEvidence
    metadata_truncated: bool = Field(strict=True)
    caption_status: Literal[
        "retrieved", "unavailable", "unsupported_format_or_language", "read_failed"
    ]
    caption_language: Literal["en", "en-orig", "en-US", "en-GB"] | None
    caption_origin: Literal["provided", "platform_automatic"] | None
    segments: tuple[TranscriptSegment, ...] = Field(max_length=MAX_SEGMENTS)
    # Includes requests made by the pinned transport's redirect handler.
    request_count: int = Field(ge=0, le=12, strict=True)
    # Separate count of yt-dlp API dispatches, which can include redirects.
    backend_request_count: int = Field(ge=0, le=12, strict=True)

    @model_validator(mode="after")
    def validate_caption_attribution(self):
        _public_youtube_url(self.metadata.source_url)
        if not _video_id(self.metadata.source_url):
            raise ValueError("A source video is required")
        if self.caption_status == "retrieved":
            if (
                not self.segments
                or not self.caption_origin
                or self.caption_language not in self.metadata.transcript_languages
            ):
                raise ValueError("Retrieved captions require source language and origin")
        elif self.segments or self.caption_language is not None or self.caption_origin is not None:
            raise ValueError("Unavailable captions cannot contain transcript text")
        for segment in self.segments:
            if (
                segment.source_url != self.metadata.source_url
                or segment.observed_at != self.metadata.observed_at
                or segment.end_seconds <= segment.start_seconds
            ):
                raise ValueError("Caption timestamp and citation source must match the video")
        return self


def parse_read_output(output: str, *, requested_url: str) -> YouTubeReadEvidence:
    if not isinstance(output, str) or len(output.encode()) > 2 * 1024 * 1024:
        raise YouTubeUnavailable("YouTube result exceeds its output bound")
    try:
        result = YouTubeReadEvidence.model_validate_json(output)
        if _video_id(_public_youtube_url(requested_url)) != _video_id(result.metadata.source_url):
            raise ValueError("Unexpected video identity")
        return result
    except (ValueError, TypeError):
        raise YouTubeUnavailable("YouTube result did not match its source contract") from None


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
    if raw.get("id") is not None and raw["id"] != _video_id(requested):
        raise YouTubeUnavailable("Video identity did not match the requested source")
    if raw.get("_type", "video") != "video":
        raise YouTubeUnavailable("Only single video metadata is supported")
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
    if int(minutes) >= 60 or int(seconds) >= 60:
        raise YouTubeUnavailable("Invalid WebVTT timestamp range")
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
    if not text.splitlines() or not re.fullmatch(r"WEBVTT(?:[ \t].*)?", text.splitlines()[0]):
        raise YouTubeUnavailable("Transcript format is unavailable")
    source = _public_youtube_url(source_url)
    if not _video_id(source):
        raise YouTubeUnavailable("Transcript source must identify a public video")
    collected_at = observed_at or datetime.now(UTC)
    segments = []
    for block in re.split(r"\n\s*\n", text)[1:]:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if lines and (lines[0] in {"STYLE", "REGION"} or re.match(r"NOTE(?:\s|$)", lines[0])):
            continue
        timing = next((line for line in lines if "-->" in line), None)
        if timing is None:
            continue
        start, _, end = timing.partition("-->")
        end = end.split(maxsplit=1)[0]
        start_seconds, end_seconds = _seconds(start), _seconds(end)
        cue = " ".join(line for line in lines[lines.index(timing) + 1 :]).strip()
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
        if len(segments) > MAX_SEGMENTS:
            raise YouTubeUnavailable("Transcript exceeds its segment limit")
    return tuple(segments)
