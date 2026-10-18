import json

import pytest

from skriller.connectors.linkedin_worker import RequestBudget, allowed_request, main, session_cookie
from skriller.security.runner import reviewed_command


@pytest.mark.parametrize(
    "url,method,kind,allowed",
    [
        (
            "https://www.linkedin.com/search/results/people/?keywords=founder",
            "GET",
            "document",
            True,
        ),
        ("https://static.licdn.com/a.js", "GET", "script", True),
        ("https://www.linkedin.com/messaging", "POST", "fetch", False),
        ("https://www.linkedin.com/checkpoint/challenge", "GET", "document", False),
        ("https://www.linkedin.com.evil.example/", "GET", "document", False),
        ("http://www.linkedin.com/", "GET", "document", False),
        ("https://user:secret@www.linkedin.com/", "GET", "document", False),
        ("https://www.linkedin.com/image", "GET", "image", False),
        ("https://www.linkedin.com:invalid/", "GET", "document", False),
    ],
)
def test_read_network_boundary(url, method, kind, allowed):
    assert bool(allowed_request(url, method, kind)) is allowed


def test_private_delivery_accepts_only_this_runners_exact_session(tmp_path, monkeypatch):
    monkeypatch.setenv("SKRILLER_LINKEDIN_WORKER", "isolated")
    monkeypatch.setattr("skriller.connectors.linkedin_worker.os.path.isfile", lambda _: True)
    path = tmp_path / "credentials.json"
    payload = {
        "schema_version": 1,
        "runner": "linkedin_search",
        "environment": {"LINKEDIN_SESSION_COOKIE": "synthetic-session"},
    }
    path.write_text(json.dumps(payload))
    assert session_cookie(path) == "synthetic-session"
    payload["environment"]["LINKEDIN_SESSION_COOKIE"] = "cookie; injected=true"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        session_cookie(path)


def test_no_arbitrary_commands_or_raw_failures(capsys):
    assert main(['{"operation":"send_message","keywords":"hello"}']) == 2
    assert capsys.readouterr().err == "LinkedIn search unavailable\n"
    with pytest.raises(ValueError):
        reviewed_command("linkedin_search", '{"operation":"shell","keywords":"test"}')


def test_navigation_retry_and_request_overflow_stop_even_partial_capture():
    url = "https://www.linkedin.com/search/results/people/?keywords=founder"
    budget = RequestBudget(url)
    assert budget.allow(url, "GET", "document")
    assert not budget.allow(url, "GET", "document") and budget.stopped
    assert not budget.allow("https://static.licdn.com/script.js", "GET", "script")
    budget = RequestBudget(url)
    for _ in range(80):
        assert budget.allow("https://static.licdn.com/script.js", "GET", "script")
    assert not budget.allow(url, "GET", "document") and budget.stopped


def test_resource_read_private_delivery_does_not_accept_search_or_extra_credentials(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("SKRILLER_LINKEDIN_WORKER", "isolated")
    monkeypatch.setattr("skriller.connectors.linkedin_worker.os.path.isfile", lambda _: True)
    path = tmp_path / "credentials.json"
    payload = {
        "schema_version": 1,
        "runner": "linkedin_resource_read",
        "environment": {"LINKEDIN_SESSION_COOKIE": "synthetic-session"},
    }
    path.write_text(json.dumps(payload))
    assert session_cookie(path, runner="linkedin_resource_read") == "synthetic-session"
    with pytest.raises(ValueError):
        session_cookie(path)
    payload["environment"]["LINKEDIN_ACCESS_TOKEN"] = "not-used-by-this-worker"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        session_cookie(path, runner="linkedin_resource_read")
