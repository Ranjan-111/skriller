"""Concrete YouTube read delegates to the existing guarded container runner."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from skriller.connectors.youtube import YouTubeReadEvidence, YouTubeUnavailable, parse_read_output
from skriller.security.runner import IsolatedRunner


@dataclass(frozen=True)
class ConcreteYouTubeExecutor:
    image: str
    docker: Path = Path("/usr/local/bin/docker")

    def __post_init__(self):
        IsolatedRunner(self.image, docker=self.docker)

    def execute(
        self, url: str, *, timeout: float = 50, cancel_check: Callable[[], bool] | None = None
    ) -> YouTubeReadEvidence:
        if not 0 < timeout <= 50:
            raise ValueError("YouTube timeout exceeds its bound")
        result = IsolatedRunner(self.image, docker=self.docker).run(
            "youtube_read",
            url,
            timeout=timeout,
            max_output=2 * 1024 * 1024,
            cancel_check=cancel_check,
        )
        if result.status != "completed":
            raise YouTubeUnavailable("Isolated YouTube read or cleanup did not complete")
        return parse_read_output(result.stdout, requested_url=url)


def public_youtube_binding(reader: ConcreteYouTubeExecutor | None = None):
    """Describe the configured public reader without probing accounts or Docker."""
    from skriller.connectors.registry import AdapterBinding
    from skriller.contracts import Capability

    def execute(context, url):
        if reader is None or context.connection_ref is not None:
            raise YouTubeUnavailable("Public YouTube reader is not configured for this route")
        remaining = (context.deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise YouTubeUnavailable("Public YouTube execution window ended")
        return reader.execute(
            url,
            timeout=min(50, remaining),
            cancel_check=lambda: context.deadline <= datetime.now(UTC),
        )

    return AdapterBinding(
        Capability(
            source="youtube",
            operation="read",
            engineering_status="tested",
            operational_status="experimental" if reader else "unavailable",
            auth_kind="none",
            access_route="Isolated public video metadata and supplied English captions; creator identity unknown",
            version="yt-dlp-2026.8.19",
            allowed_fields=[
                "public_video_metadata",
                "provided_captions",
                "platform_automatic_captions",
            ],
        ),
        "isolated_public_youtube",
        execute,
    )
