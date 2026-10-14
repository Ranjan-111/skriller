import base64
import json
from pathlib import Path

import pytest

from skriller.connectors.browser import BrowserRequest
from skriller.connectors.browser_executor import ConcreteBrowserExecutor
from skriller.connectors.fetch import FetchUnavailable
from skriller.security.runner import RunResult

IMAGE = "worker@sha256:" + "a" * 64


def test_concrete_executor_fixed_guarded_args_bounded_json_and_cleanup(monkeypatch):
    from skriller.connectors import browser_executor as module

    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[1] == "rm":
            assert kwargs.get("cancel_check") is None
            return RunResult("completed", 0, "", "", 1)
        assert (
            json.loads((kwargs["cwd"] / "request.json").read_bytes())["url"]
            == "https://example.com"
        )
        assert (kwargs["cwd"] / "request.json").stat().st_mode & 0o777 == 0o600
        assert not any(key in kwargs["env"] for key in ["GH_TOKEN", "HOST_SECRET", "GROQ_API_KEY"])
        return RunResult(
            "completed",
            0,
            json.dumps(
                {
                    "content_base64": base64.b64encode(b"<h1>Fixture</h1>").decode(),
                    "final_url": "https://example.com",
                    "status": 200,
                    "request_count": 1,
                    "elapsed_seconds": 0.1,
                }
            ),
            "",
            1,
        )

    monkeypatch.setattr(module, "bounded_process", run)
    monkeypatch.setenv("HOST_SECRET", "secret")
    result = ConcreteBrowserExecutor(IMAGE).execute(
        BrowserRequest("https://example.com", "h1", 10, 2)
    )
    assert result.content == b"<h1>Fixture</h1>"
    argv, kwargs = calls[0]
    assert argv[argv.index("--network") + 1] == "skriller_egress_workers"
    assert "--read-only" in argv and "no-new-privileges:true" in argv
    assert argv[argv.index("--mount") + 1].endswith("target=/work,readonly")
    assert "--tmpfs" in argv and "SKRILLER_BROWSER_WORKER=isolated" in argv
    assert argv[-4:] == ["python", "-m", "skriller.connectors.browser_worker", "/work/request.json"]
    assert calls[1][0][-1] == argv[argv.index("--name") + 1]
    assert not Path(kwargs["cwd"]).exists()


@pytest.mark.parametrize(
    "status,code",
    [
        ("timeout", "deadline_exceeded"),
        ("cancelled", "cancelled"),
        ("failed", "source_unavailable"),
    ],
)
def test_concrete_executor_failure_always_cleans_container(monkeypatch, status, code):
    from skriller.connectors import browser_executor as module

    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return RunResult("completed" if argv[1] == "rm" else status, 0, "", "", 1)

    monkeypatch.setattr(module, "bounded_process", run)
    with pytest.raises(FetchUnavailable) as failure:
        ConcreteBrowserExecutor(IMAGE).execute(BrowserRequest("https://example.com", "h1", 10, 2))
    assert failure.value.failure.code == code and len(calls) == 2


def test_concrete_executor_pre_cancel_performs_no_io(monkeypatch):
    from skriller.connectors import browser_executor as module

    monkeypatch.setattr(module, "bounded_process", lambda *_args, **_kwargs: pytest.fail("No IO"))
    with pytest.raises(FetchUnavailable) as failure:
        ConcreteBrowserExecutor(IMAGE).execute(
            BrowserRequest("https://example.com", "h1", 10, 2), cancel_check=lambda: True
        )
    assert failure.value.failure.code == "cancelled"


@pytest.mark.parametrize(
    "changes",
    [
        {"timeout_seconds": float("nan")},
        {"max_requests": True},
        {"max_body_bytes": True},
        {"timeout_seconds": True},
    ],
)
def test_browser_wire_limits_reject_ambiguous_values(changes):
    data = {
        "url": "https://example.com",
        "readiness_selector": "h1",
        "timeout_seconds": 10,
        "max_requests": 2,
    }
    with pytest.raises(ValueError):
        BrowserRequest(**{**data, **changes})
