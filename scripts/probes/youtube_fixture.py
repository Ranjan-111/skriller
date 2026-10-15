"""Network-none installed yt-dlp integration fixture; never a public-source trial."""

import io
import json
import os
import subprocess
from importlib.metadata import version
from pathlib import Path

from agent_reach.channels.youtube import YouTubeChannel
from yt_dlp.extractor.common import InfoExtractor

from skriller.connectors.youtube import parse_read_output
from skriller.connectors.youtube_worker import BoundedYoutubeDL, read_video

URL = "https://www.youtube.com/watch?v=fixture123"
CAPTION = "https://www.youtube.com/api/timedtext?secret=synthetic-signed-value"


class FixtureIE(InfoExtractor):
    _VALID_URL = r"https://www.youtube.com/watch\?v=(?P<id>fixture123)$"

    def _real_extract(self, url):
        return {
            "id": "fixture123",
            "title": "Synthetic public creator",
            "webpage_url": URL,
            "duration": 3.5,
            "view_count": 42,
            "formats": [{"url": "https://www.youtube.com/fixture-video.mp4", "ext": "mp4"}],
            "subtitles": {"en": [{"url": CAPTION, "ext": "vtt"}]},
        }


class FixtureBackend(BoundedYoutubeDL):
    def __init__(self, params):
        super().__init__(params)
        self.add_info_extractor(FixtureIE())

    def extract_info(self, url, download=False):
        return super().extract_info(url, download=download, ie_key=FixtureIE.ie_key())

    def urlopen(self, request):
        if request != CAPTION:
            raise AssertionError("Fixture cannot perform network requests")
        self.backend_request_count += 1
        self.request_count += 1
        return io.BytesIO(
            b"WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n<c>We build public tools.</c>\n"
        )


def main():
    assert Path("/.dockerenv").is_file()
    assert os.getuid() != 0
    assert "CapEff:\t0000000000000000" in Path("/proc/self/status").read_text()
    assert version("yt-dlp") == "2026.8.19"
    channel = YouTubeChannel()
    runtime_status, _ = channel.check()
    assert channel.active_backend == "yt-dlp" and runtime_status in {"ok", "warn"}
    node_version = subprocess.run(
        ["/usr/local/bin/node", "--version"], check=True, capture_output=True, text=True, timeout=5
    ).stdout.strip()
    report = read_video(URL, backend_factory=FixtureBackend)
    record = parse_read_output(json.dumps(report), requested_url=URL)
    assert record.metadata.view_count == 42
    assert record.metadata.counter_scope == "public_metadata"
    assert record.caption_status == "retrieved"
    assert record.segments[0].source_url == URL
    assert record.segments[0].start_seconds == 1
    assert record.segments[0].text == "We build public tools."
    assert "synthetic-signed-value" not in json.dumps(report)
    print(
        json.dumps(
            {
                "backend_version": version("yt-dlp"),
                "actual_extractor_pipeline": True,
                "caption_citation_verified": True,
                "network": "none",
                "unprivileged": True,
                "source_live_verified": False,
                "node_version": node_version,
                "agent_reach_runtime_status": runtime_status,
            }
        )
    )


if __name__ == "__main__":
    main()
