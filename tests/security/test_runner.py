import os
import sys
import time

import pytest

from skriller.security.runner import IsolatedRunner, bounded_process, reviewed_command


def test_shell_and_write_operations_never_form_commands():
    with pytest.raises(ValueError, match="Unsupported"):
        reviewed_command("shell", "$(cat ~/.ssh/id_rsa)")
    with pytest.raises(ValueError):
        reviewed_command("youtube_metadata", "https://youtube.com;touch /tmp/pwned")
    command = reviewed_command("youtube_metadata", "https://youtube.com/watch?v=abc&x=$(id)")
    assert command[-2] == "--"
    assert "$(id)" in command[-1]
    assert "--ignore-config" in command


def test_mutable_image_or_network_bypass_configuration_rejected():
    with pytest.raises(ValueError, match="immutable"):
        IsolatedRunner(image="worker:latest")
    with pytest.raises(ValueError, match="topology"):
        IsolatedRunner(image="worker@sha256:" + "a" * 64, network="host")


def test_process_timeout_kills_descendant_process_group(tmp_path):
    marker = tmp_path / "escaped-child"
    # If process-group termination is missing, the detached child writes later.
    child = (
        f"import time,pathlib; time.sleep(1); pathlib.Path({str(marker)!r}).write_text('escaped')"
    )
    parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(20)"
    result = bounded_process(
        [sys.executable, "-c", parent], cwd=tmp_path, env={"PATH": "/usr/bin:/bin"}, timeout=0.2
    )
    assert result.status == "timeout"
    time.sleep(1.1)
    assert not marker.exists()


def test_combined_output_limit_terminates_flood_without_deadlock(tmp_path):
    code = "import os;\nwhile True: os.write(1,b'x'*65536); os.write(2,b'y'*65536)"
    result = bounded_process(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        max_output=1024,
        timeout=2,
    )
    assert result.status == "output_limit"
    assert len(result.stdout.encode()) + len(result.stderr.encode()) <= 1024


def test_minimal_environment_and_utf8_redaction(tmp_path, monkeypatch):
    monkeypatch.setenv("SKRILLER_TEST_HOST_SECRET", "host-secret")
    code = "import os; print(os.getenv('SKRILLER_TEST_HOST_SECRET')); print('https://u:pass@proxy.test/?token=secret'); print('東京')"
    result = bounded_process(
        [sys.executable, "-c", code], cwd=tmp_path, env={"PATH": "/usr/bin:/bin", "PYTHONUTF8": "1"}
    )
    assert result.status == "completed"
    assert "None" in result.stdout
    assert "host-secret" not in result.stdout
    assert "pass" not in result.stdout
    assert "secret" not in result.stdout
    assert "東京" in result.stdout


def test_missing_executable_has_typed_unavailable_result(tmp_path):
    result = bounded_process(
        [str(tmp_path / "missing-backend")], cwd=tmp_path, env={"PATH": "/usr/bin:/bin"}
    )
    assert result.status == "unavailable"
    assert result.returncode is None
    assert result.stdout == ""


def test_runner_only_mounts_task_workspace_and_removes_container(monkeypatch):
    from skriller.security import runner

    calls = []

    def execute(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[1:3] == ["rm", "-f"]:
            return runner.RunResult("completed", 0, "", "", 1)
        return runner.RunResult("timeout", -9, "", "", 1)

    monkeypatch.setattr(runner, "bounded_process", execute)
    monkeypatch.setattr(os, "environ", {"HOST_SECRET": "secret", "GH_TOKEN": "token"})
    result = IsolatedRunner(image="worker@sha256:" + "a" * 64).run(
        "youtube_metadata", "https://youtu.be/abc"
    )
    assert result.status == "timeout"
    argv, kwargs = calls[0]
    assert "--read-only" in argv
    assert "--cap-drop" in argv
    assert "/usr/local/bin/guarded-worker" in argv
    mounts = [argv[index + 1] for index, value in enumerate(argv) if value == "--mount"]
    assert len(mounts) == 1 and mounts[0].endswith("target=/work")
    assert not any("HOST_SECRET" in value or "GH_TOKEN" in value for value in argv)
    assert kwargs["env"] == {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    assert calls[1][0][1:3] == ["rm", "-f"]
    assert calls[1][0][-1] == argv[argv.index("--name") + 1]


def test_failed_container_cleanup_is_not_silent_success(monkeypatch):
    from skriller.security import runner

    def execute(argv, **kwargs):
        if argv[1:3] == ["rm", "-f"]:
            return runner.RunResult("failed", 1, "", "daemon unavailable", 1)
        return runner.RunResult("completed", 0, "result", "", 1)

    monkeypatch.setattr(runner, "bounded_process", execute)
    result = IsolatedRunner(image="worker@sha256:" + "a" * 64).run(
        "youtube_metadata", "https://youtu.be/abc"
    )
    assert result.status == "cleanup_failed"


@pytest.mark.parametrize("closed_pipes", [False, True])
def test_persisted_control_cancels_parent_and_descendant_group(tmp_path, closed_pipes):
    import threading

    marker = tmp_path / "late-child"
    ready = tmp_path / "ready"
    stopped = threading.Event()
    child = f"import time,pathlib; time.sleep(1); pathlib.Path({str(marker)!r}).write_text('late')"
    parent = (
        f"import os,subprocess,sys,time,pathlib; subprocess.Popen([sys.executable,'-c',{child!r}]); "
        f"pathlib.Path({str(ready)!r}).write_text('ready'); "
        + ("os.close(1); os.close(2); " if closed_pipes else "")
        + "time.sleep(20)"
    )

    def cancel_check():
        if ready.exists():
            stopped.set()
        return stopped.is_set()

    started = time.monotonic()
    result = bounded_process(
        [sys.executable, "-c", parent],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        timeout=20,
        cancel_check=cancel_check,
    )
    assert result.status == "cancelled" and result.returncode == -9
    assert time.monotonic() - started < 5
    time.sleep(1.1)
    assert not marker.exists()


@pytest.mark.parametrize("error", [False, True])
def test_process_stop_before_launch_performs_no_io(tmp_path, monkeypatch, error):
    from skriller.security import runner

    def check():
        if error:
            raise RuntimeError("private control database token")
        return True

    monkeypatch.setattr(
        runner.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("No launch")
    )
    result = bounded_process(
        [sys.executable, "-c", "raise AssertionError"], cwd=tmp_path, env={}, cancel_check=check
    )
    assert result.status == ("control_unavailable" if error else "cancelled")
    assert result.returncode is None and result.stdout == "" and result.stderr == ""


def test_control_error_while_running_fails_closed_and_kills_group(tmp_path):
    ready = tmp_path / "ready"
    marker = tmp_path / "late"
    code = f"import pathlib,time; pathlib.Path({str(ready)!r}).write_text('ready'); time.sleep(1); pathlib.Path({str(marker)!r}).write_text('late')"

    def check():
        if ready.exists():
            raise RuntimeError("private database password")
        return False

    result = bounded_process([sys.executable, "-c", code], cwd=tmp_path, env={}, cancel_check=check)
    assert result.status == "control_unavailable" and result.returncode == -9
    assert "password" not in result.stderr
    time.sleep(1.1)
    assert not marker.exists()


def test_runner_cancel_always_cleans_unique_container_with_uncancelled_cleanup(monkeypatch):
    from skriller.security import runner

    calls = []
    checks = iter([False, True])

    def check():
        return next(checks)

    def execute(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[1:3] == ["rm", "-f"]:
            assert kwargs.get("cancel_check") is None
            return runner.RunResult("completed", 0, "", "", 1)
        assert kwargs["cancel_check"]() is True
        return runner.RunResult("cancelled", -9, "", "", 1)

    monkeypatch.setattr(runner, "bounded_process", execute)
    result = IsolatedRunner(image="worker@sha256:" + "a" * 64).run(
        "youtube_metadata", "https://youtu.be/abc", cancel_check=check
    )
    assert result.status == "cancelled"
    assert len(calls) == 2
    assert calls[1][0][-1] == calls[0][0][calls[0][0].index("--name") + 1]


def test_runner_preexisting_cancel_performs_no_docker_io(monkeypatch):
    from skriller.security import runner

    monkeypatch.setattr(
        runner, "bounded_process", lambda *_args, **_kwargs: pytest.fail("No docker")
    )
    result = IsolatedRunner(image="worker@sha256:" + "a" * 64).run(
        "youtube_metadata", "https://youtu.be/abc", cancel_check=lambda: True
    )
    assert result.status == "cancelled"
