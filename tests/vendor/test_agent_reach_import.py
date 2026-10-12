"""SKR-003 source closure and offline diagnostics; never launch platform CLIs."""
import importlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "third_party" / "agent-reach"


def test_agent_reach_provenance_and_test_closure():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/provenance.py"), "verify", "agent-reach"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((VENDOR / "PROVENANCE.json").read_text())
    names = {item["path"] for item in manifest["files"]}
    assert {
        "LICENSE", "pyproject.toml", "agent_reach/channels/linkedin.py",
        "agent_reach/channels/reddit.py", "agent_reach/doctor.py",
        "tests/conftest.py", "tests/test_channel_contracts.py",
        "tests/test_url_security.py", "tests/test_scrub_credentials.py",
    } <= names


@pytest.mark.parametrize("module", [
    "agent_reach", "agent_reach.channels", "agent_reach.utils.url",
    "agent_reach.utils.text", "agent_reach.doctor",
])
def test_installed_import_resolves_to_copied_tree(tmp_path, module):
    result = subprocess.run(
        [sys.executable, "-I", "-c",
         f"import importlib,pathlib; print(pathlib.Path(importlib.import_module({module!r}).__file__).resolve())"],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert Path(result.stdout.strip()).is_relative_to(VENDOR)


@pytest.fixture
def contained_runtime(monkeypatch, tmp_path):
    import urllib.request
    from urllib.error import URLError

    from agent_reach.config import Config

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(Config, "CONFIG_DIR", tmp_path / ".agent-reach")
    monkeypatch.setattr(Config, "CONFIG_FILE", tmp_path / ".agent-reach/config.yaml")
    monkeypatch.setattr("shutil.which", lambda command: None)

    def offline(*args, **kwargs):
        raise URLError("offline test: no platform requests")

    def no_process(*args, **kwargs):
        pytest.fail("diagnostics launched an external process")

    monkeypatch.setattr(urllib.request, "urlopen", offline)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", offline)
    monkeypatch.setattr(subprocess, "run", no_process)
    return Config(config_path=tmp_path / "config.yaml")


def test_no_cli_diagnostics_do_not_claim_external_backends_ready(contained_runtime):
    from agent_reach.channels import get_all_channels
    # Registry contains mutable singleton instances: use new instances so this
    # test cannot inherit an active backend set by another workspace/check.
    channels = {channel.name: type(channel)() for channel in get_all_channels()}
    for name in ("github", "linkedin", "reddit", "twitter", "facebook",
                 "instagram", "xiaohongshu", "exa_search", "youtube", "boss"):
        channel = channels[name]
        status, message = channel.check(contained_runtime)
        assert status != "ok", (name, status, message)
        assert channel.active_backend is None, name
        assert message.strip(), name


def test_linkedin_configuration_is_not_verified_access(contained_runtime, monkeypatch):
    module = importlib.import_module("agent_reach.channels.linkedin")
    monkeypatch.setattr("shutil.which", lambda command: "/isolated/" + command)
    monkeypatch.setattr(module, "inspect_mcporter_config", lambda: SimpleNamespace(
        server_names={"linkedin"}, imports_unchecked=False,
    ))
    channel = module.LinkedInChannel()
    status, message = channel.check(contained_runtime)
    assert status == "warn"
    assert channel.active_backend is None
    assert message.strip()


def test_reddit_saved_cookie_is_not_verified_access(contained_runtime, monkeypatch, tmp_path):
    module = importlib.import_module("agent_reach.channels.reddit")
    monkeypatch.setattr("shutil.which", lambda command: "/isolated/rdt" if command == "rdt" else None)
    credentials = tmp_path / ".config/rdt-cli/credential.json"
    credentials.parent.mkdir(parents=True)
    credentials.write_text(json.dumps({"cookies": {"reddit_session": "test-only-cookie"}}))
    credentials.chmod(0o600)
    channel = module.RedditChannel()
    status, message = channel.check(contained_runtime)
    assert status == "warn"
    assert channel.active_backend is None
    assert "test-only-cookie" not in message
