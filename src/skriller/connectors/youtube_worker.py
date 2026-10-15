"""Isolated glue around Agent-Reach's installed yt-dlp backend, not a scraper engine."""

import json
import os
import sys
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from time import monotonic

from agent_reach.utils.url import host_matches, normalize_public_http_url
from yt_dlp import YoutubeDL
from yt_dlp.networking._urllib import RedirectHandler, UrllibRH

from skriller.connectors.youtube import (
    YouTubeReadEvidence,
    _public_youtube_url,
    _video_id,
    parse_metadata_output,
    parse_webvtt,
)

MAX_BACKEND_REQUESTS = 12
MAX_CAPTION_BYTES = 131072


class SilentLogger:
    def debug(self, message):
        pass

    info = debug
    warning = debug
    error = debug


class BoundedYoutubeDL(YoutubeDL):
    """Reuse pinned yt-dlp urllib transport, metering requests and redirects."""

    def __init__(self, params):
        self.backend_request_count = 0
        self.request_count = 0
        self.deadline = monotonic() + 40
        super().__init__(params)

    def permit_request(self, url):
        normalize_public_http_url(url)
        if monotonic() >= self.deadline or self.request_count >= MAX_BACKEND_REQUESTS:
            raise TimeoutError("HTTP request bound reached")
        self.request_count += 1

    @cached_property
    def _request_director(self):
        # No alternate handler can perform an unmetered fallback. Reuse the
        # backend's TLS, HTTP, redirect and cookie machinery without a new client.
        owner = self

        class MeteredUrllibRH(UrllibRH):
            def _send(self, request):
                owner.permit_request(request.url)
                return super()._send(request)

            def _create_instance(self, *args, **kwargs):
                opener = super()._create_instance(*args, **kwargs)
                handler = next(
                    item for item in opener.handlers if isinstance(item, RedirectHandler)
                )
                original = handler.redirect_request

                def checked_redirect(req, fp, code, msg, headers, newurl):
                    redirect = original(req, fp, code, msg, headers, newurl)
                    if redirect is not None:
                        owner.permit_request(redirect.full_url)
                    return redirect

                handler.redirect_request = checked_redirect
                return opener

        return self.build_request_director([MeteredUrllibRH])

    def urlopen(self, req):
        normalize_public_http_url(req if isinstance(req, str) else req.url)
        if monotonic() >= self.deadline or self.backend_request_count >= MAX_BACKEND_REQUESTS:
            raise TimeoutError("Backend request bound reached")
        self.backend_request_count += 1
        return super().urlopen(req)


def _caption(raw):
    for origin, key in (("provided", "subtitles"), ("platform_automatic", "automatic_captions")):
        mapping = raw.get(key)
        if not isinstance(mapping, dict):
            continue
        for language in ("en", "en-orig", "en-US", "en-GB"):
            entries = mapping.get(language)
            if not isinstance(entries, list):
                continue
            for item in entries[:100]:
                if not isinstance(item, dict) or item.get("ext") != "vtt":
                    continue
                try:
                    url = normalize_public_http_url(item.get("url"))
                    if not host_matches(url, "youtube.com", "googlevideo.com"):
                        continue
                except (TypeError, ValueError):
                    continue
                return language, origin, url
    return None


def read_video(url, *, backend_factory=None):
    """The injection seam is for synthetic tests; real reads require the container."""
    if backend_factory is None:
        if (
            os.environ.get("SKRILLER_YOUTUBE_WORKER") != "isolated"
            or not Path("/.dockerenv").is_file()
        ):
            raise RuntimeError("YouTube requires an isolated worker")
        backend_factory = BoundedYoutubeDL
    url = _public_youtube_url(url)
    video_id = _video_id(url)
    if not video_id:
        raise ValueError("A single video URL is required")
    options = {
        "quiet": True,
        "no_warnings": True,
        "logger": SilentLogger(),
        "noplaylist": True,
        "skip_download": True,
        "extract_flat": False,
        "socket_timeout": 8,
        "retries": 0,
        "extractor_retries": 0,
        "fragment_retries": 0,
        "cachedir": False,
        "js_runtimes": {"node": {"path": "/usr/local/bin/node"}},
        "remote_components": set(),
        "proxy": "http://172.29.0.2:8080",
    }
    with backend_factory(options) as backend:
        raw = backend.extract_info(url, download=False)
        if (
            not isinstance(raw, dict)
            or raw.get("id") != video_id
            or raw.get("_type", "video") != "video"
        ):
            raise ValueError("Metadata must identify the requested single video")
        selected = {
            key: raw.get(key)
            for key in (
                "id",
                "webpage_url",
                "title",
                "channel",
                "uploader",
                "channel_url",
                "uploader_url",
                "upload_date",
                "duration",
                "view_count",
                "like_count",
                "description",
                "subtitles",
                "automatic_captions",
            )
        }
        truncated = False
        for key, limit in (
            ("title", 500),
            ("channel", 300),
            ("uploader", 300),
            ("description", 8192),
        ):
            value = selected.get(key)
            if isinstance(value, str) and len(value) > limit:
                selected[key] = value[:limit]
                truncated = True
        # Signed caption endpoints stay inside the worker. The public result
        # retains language availability only, never a credential-bearing URL.
        for key in ("subtitles", "automatic_captions"):
            mapping = selected.get(key)
            selected[key] = (
                {name: [] for name in list(mapping)[:30]} if isinstance(mapping, dict) else {}
            )
        observed_at = datetime.now(UTC)
        metadata = parse_metadata_output(
            json.dumps(selected, allow_nan=False), requested_url=url, observed_at=observed_at
        )
        result = {
            "metadata": metadata.model_dump(mode="json"),
            "metadata_truncated": truncated,
            "caption_status": "unavailable"
            if not metadata.transcript_languages
            else "unsupported_format_or_language",
            "caption_language": None,
            "caption_origin": None,
            "segments": [],
        }
        caption = _caption(raw)
        if caption is not None:
            language, origin, caption_url = caption
            try:
                with backend.urlopen(caption_url) as response:
                    content = response.read(MAX_CAPTION_BYTES + 1)
                if len(content) > MAX_CAPTION_BYTES:
                    raise ValueError("Caption size bound reached")
                segments = parse_webvtt(
                    content, source_url=metadata.source_url, observed_at=observed_at
                )
                if not segments:
                    raise ValueError("No source caption cues returned")
                result.update(
                    caption_status="retrieved",
                    caption_language=language,
                    caption_origin=origin,
                    segments=[segment.model_dump(mode="json") for segment in segments],
                )
            except Exception:  # noqa: BLE001 - preserve metadata, redact signed URLs/backend errors
                result["caption_status"] = "read_failed"
        result["backend_request_count"] = backend.backend_request_count
        result["request_count"] = backend.request_count
        return YouTubeReadEvidence.model_validate(result).model_dump(mode="json")


def main():
    try:
        if len(sys.argv) != 2:
            raise ValueError("One video required")
        print(json.dumps(read_video(sys.argv[1]), allow_nan=False, separators=(",", ":")))
        return 0
    except Exception as error:  # noqa: BLE001 - never print private URLs, SDK errors or tracebacks
        category = "backend" if type(error).__name__ == "DownloadError" else "runtime_or_schema"
        print(json.dumps({"error": "source_unavailable", "category": category}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
