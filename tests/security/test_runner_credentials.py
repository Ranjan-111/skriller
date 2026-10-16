"""Credential channel checks; synthetic material only, no account access."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr

from skriller.connections.store import RunnerSecrets
from skriller.security import runner


def material():
    return RunnerSecrets(
        uuid4(),
        "linkedin_read",
        {"LINKEDIN_SESSION_COOKIE": SecretStr("synthetic-worker-secret")},
        uuid4(),
    )


@pytest.mark.parametrize("raises", [False, True])
def test_private_readonly_file_delivery_and_cleanup_never_use_secret_argv_or_env(
    monkeypatch, raises
):
    captured = []
    monkeypatch.setattr(runner, "reviewed_command", lambda *_: ["python", "-c", "pass"])

    def execute(argv, **kwargs):
        if argv[1] == "rm":
            return runner.RunResult("completed", 0, "", "", 1)
        assert "synthetic-worker-secret" not in str(argv) + str(kwargs["env"])
        assert argv[argv.index("--log-driver") + 1] == "none"
        mount = next(item for item in argv if "target=/run/skriller-credentials.json" in item)
        assert mount.endswith(",readonly")
        path = Path(mount.split("source=", 1)[1].split(",", 1)[0])
        captured.append(path)
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
        assert json.loads(path.read_bytes())["environment"] == {
            "LINKEDIN_SESSION_COOKIE": "synthetic-worker-secret"
        }
        if raises:
            raise OSError("controlled fixture failure")
        return runner.RunResult("completed", 0, "synthetic-worker-secret", "secret error", 1)

    monkeypatch.setattr(runner, "bounded_process", execute)
    invoke = lambda: runner.IsolatedRunner(image="sha256:" + "a" * 64).run(
        "linkedin_read", "fixture", credential_material=material()
    )
    if raises:
        with pytest.raises(OSError):
            invoke()
    else:
        result = invoke()
        assert "synthetic-worker-secret" not in result.stdout
        assert result.stderr == ""
    assert captured and not captured[0].parent.exists()


def test_source_mismatch_or_unknown_credential_fields_are_refused_before_launch(monkeypatch):
    monkeypatch.setattr(runner, "reviewed_command", lambda *_: ["python", "-c", "pass"])
    monkeypatch.setattr(runner, "bounded_process", lambda *_a, **_k: pytest.fail("No dispatch"))
    isolated = runner.IsolatedRunner(image="sha256:" + "a" * 64)
    with pytest.raises(ValueError, match="fixed source"):
        isolated.run("youtube_read", "fixture", credential_material=material())
    bad = RunnerSecrets(uuid4(), "linkedin_read", {"HOST_SECRET": SecretStr("fixture")})
    with pytest.raises(ValueError, match="fixed source"):
        isolated.run("linkedin_read", "fixture", credential_material=bad)
