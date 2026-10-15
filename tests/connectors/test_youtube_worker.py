import io
import json

import pytest

from skriller.connectors import youtube_worker as worker
from skriller.connectors.youtube import YouTubeUnavailable, parse_read_output
from skriller.connectors.youtube_executor import ConcreteYouTubeExecutor
from skriller.security.runner import reviewed_command

URL = "https://www.youtube.com/watch?v=fixture123"
CAPTION_URL = "https://www.youtube.com/api/timedtext?secret=signed-fixture"
VTT = b"WEBVTT\n\n00:00:01.250 --> 00:00:03.000\n<c>We build public tools.</c>\n"


class FixtureBackend:
    def __init__(self, options, *, captions=True, content=VTT, fail=False, wrong_id=False):
        assert options["skip_download"] and options["noplaylist"]
        assert options["retries"] == options["extractor_retries"] == 0
        assert options["js_runtimes"] == {"node": {"path": "/usr/local/bin/node"}}
        assert options["remote_components"] == set()
        assert options["cachedir"] is False
        self.backend_request_count = 0
        self.request_count = 0
        self.captions, self.content, self.fail, self.wrong_id = captions, content, fail, wrong_id

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def extract_info(self, url, *, download):
        assert url == URL and download is False
        self.backend_request_count += 1
        self.request_count += 1
        return {
            "id": "wrong" if self.wrong_id else "fixture123",
            "webpage_url": URL,
            "title": "Synthetic creator interview",
            "duration": 3.5,
            "view_count": 5,
            "like_count": 1,
            "subtitles": {"en": [{"ext": "vtt", "url": CAPTION_URL}]} if self.captions else {},
        }

    def urlopen(self, url):
        assert url == CAPTION_URL
        self.backend_request_count += 1
        self.request_count += 1
        if self.fail:
            raise RuntimeError("secret signed-fixture backend exception")
        return io.BytesIO(self.content)


def test_no_captions_retains_public_metadata_without_generating_text():
    report = worker.read_video(
        URL, backend_factory=lambda options: FixtureBackend(options, captions=False)
    )
    assert report["metadata"]["counter_scope"] == "public_metadata"
    assert report["metadata"]["duration_seconds"] == 3.5
    assert report["metadata"]["view_count"] == 5
    assert report["caption_status"] == "unavailable"
    assert report["segments"] == [] and report["backend_request_count"] == 1


def test_supplied_caption_keeps_quote_timestamp_and_source_and_redacts_signed_url():
    report = worker.read_video(URL, backend_factory=FixtureBackend)
    assert report["caption_status"] == "retrieved"
    assert report["caption_origin"] == "provided"
    assert report["caption_language"] == "en"
    assert report["backend_request_count"] == 2
    (segment,) = report["segments"]
    assert (segment["start_seconds"], segment["end_seconds"]) == (1.25, 3)
    assert segment["text"] == "We build public tools."
    assert segment["source_url"] == URL
    assert "signed-fixture" not in json.dumps(report)


@pytest.mark.parametrize(
    "changes",
    [
        {"fail": True},
        {"content": b"not captions"},
        {"content": b"x" * (worker.MAX_CAPTION_BYTES + 1)},
    ],
)
def test_caption_read_failure_preserves_metadata_and_does_not_expose_backend_error(changes):
    report = worker.read_video(
        URL, backend_factory=lambda options: FixtureBackend(options, **changes)
    )
    assert report["metadata"]["title"] == "Synthetic creator interview"
    assert report["caption_status"] == "read_failed" and report["segments"] == []
    assert "signed-fixture" not in json.dumps(report)


def test_wrong_video_identity_stops_before_caption_retrieval():
    with pytest.raises(ValueError, match="requested single video"):
        worker.read_video(
            URL, backend_factory=lambda options: FixtureBackend(options, wrong_id=True)
        )


def test_actual_backend_cannot_start_on_host_without_container():
    with pytest.raises(RuntimeError, match="isolated"):
        worker.read_video(URL)


def test_only_reviewed_module_command_is_generated():
    assert reviewed_command("youtube_read", URL) == [
        "python",
        "-m",
        "skriller.connectors.youtube_worker",
        URL,
    ]
    with pytest.raises(ValueError):
        reviewed_command("youtube_read", "https://youtube.com.evil.example/watch?v=fixture123")


def test_backend_dispatch_counter_refuses_over_budget_before_next_call(monkeypatch):
    monkeypatch.setattr(worker.YoutubeDL, "urlopen", lambda self, request: "synthetic response")
    with worker.BoundedYoutubeDL({"quiet": True, "logger": worker.SilentLogger()}) as backend:
        for _ in range(worker.MAX_BACKEND_REQUESTS):
            assert backend.urlopen(URL) == "synthetic response"
        with pytest.raises(TimeoutError):
            backend.urlopen(URL)
        assert backend.backend_request_count == worker.MAX_BACKEND_REQUESTS


def test_worker_output_is_source_bound_before_host_use():
    data = worker.read_video(URL, backend_factory=FixtureBackend)
    parsed = parse_read_output(json.dumps(data), requested_url=URL)
    assert parsed.segments[0].text == "We build public tools."
    with pytest.raises(YouTubeUnavailable):
        parse_read_output(json.dumps(data), requested_url="https://youtu.be/another1234")
    data["segments"][0]["source_url"] = "https://youtu.be/another1234"
    with pytest.raises(YouTubeUnavailable):
        parse_read_output(json.dumps(data), requested_url=URL)


@pytest.mark.parametrize(
    "field,value",
    [("backend_request_count", 13), ("caption_origin", None), ("caption_status", "unavailable")],
)
def test_forged_worker_limits_or_caption_state_are_rejected(field, value):
    data = worker.read_video(URL, backend_factory=FixtureBackend)
    data[field] = value
    with pytest.raises(YouTubeUnavailable):
        parse_read_output(json.dumps(data), requested_url=URL)


def test_executor_uses_guarded_runner_and_never_uses_raw_failure_text(monkeypatch):
    from skriller.security.runner import IsolatedRunner, RunResult

    report = worker.read_video(URL, backend_factory=FixtureBackend)
    calls = []

    def run(self, operation, target, **kwargs):
        calls.append((operation, target, kwargs))
        return RunResult("completed", 0, json.dumps(report), "", 1)

    monkeypatch.setattr(IsolatedRunner, "run", run)
    executor = ConcreteYouTubeExecutor("sha256:" + "a" * 64)
    assert executor.execute(URL).caption_status == "retrieved"
    assert calls[0][0] == "youtube_read" and calls[0][2]["max_output"] == 2 * 1024 * 1024
    monkeypatch.setattr(
        IsolatedRunner,
        "run",
        lambda *args, **kwargs: RunResult("cleanup_failed", 1, "", "private error", 1),
    )
    with pytest.raises(YouTubeUnavailable, match="cleanup") as error:
        executor.execute(URL)
    assert "private error" not in str(error.value)


def test_pinned_transport_counts_redirects_and_has_no_unmetered_fallback(monkeypatch):
    import urllib.request

    from yt_dlp.networking import Request
    from yt_dlp.networking._urllib import RedirectHandler, UrllibRH

    monkeypatch.setattr(UrllibRH, "_send", lambda self, request: "synthetic response")
    with worker.BoundedYoutubeDL({"quiet": True, "logger": worker.SilentLogger()}) as backend:
        handlers = list(backend._request_director.handlers.values())
        assert len(handlers) == 1
        handler = handlers[0]
        assert handler._send(Request(URL)) == "synthetic response"
        assert backend.request_count == 1
        opener = handler._create_instance(proxies={}, cookiejar=backend.cookiejar)
        redirect = next(item for item in opener.handlers if isinstance(item, RedirectHandler))
        redirected = redirect.redirect_request(
            urllib.request.Request(URL), None, 302, "Found", {}, CAPTION_URL
        )
        assert redirected.full_url == CAPTION_URL and backend.request_count == 2
        with pytest.raises(ValueError):
            redirect.redirect_request(
                urllib.request.Request(URL), None, 302, "Found", {}, "http://127.0.0.1/private"
            )
        assert backend.request_count == 2


def test_youtube_configuration_requires_proxy_and_immutable_image():
    from skriller.settings import Settings

    with pytest.raises(ValueError, match="guarded"):
        Settings(_env_file=None, public_youtube_image="sha256:" + "a" * 64)
    with pytest.raises(ValueError, match="immutable"):
        Settings(
            _env_file=None,
            public_collection_proxy_url="http://127.0.0.1:8080",
            public_youtube_image="reader:latest",
        )
