"""Actual digest-pinned guarded worker cancellation, no source/backend credentials."""

import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from test_budget import job_fixture

from skriller.db import JobRepository
from skriller.jobs.control import cancel
from skriller.security.runner import IsolatedRunner

pytestmark = pytest.mark.integration_db


def test_actual_container_parent_and_descendant_are_removed_after_persisted_cancel(
    database, monkeypatch
):
    if os.environ.get("SKRILLER_EGRESS_CONTAINER_TESTS") != "1":
        pytest.skip("Requires existing digest-pinned worker fixture and healthy Docker")
    from skriller.security import runner

    # This trusted test replaces only the reviewed command with a fixed fixture.
    # Production operation/URL allowlisting is unchanged; no source call occurs.
    code = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c',"
        "\"import time; print('descendant-ready',flush=True); time.sleep(30)\"]); "
        "print('parent-ready',flush=True); time.sleep(30)"
    )
    monkeypatch.setattr(runner, "reviewed_command", lambda *_: ["python", "-c", code])
    docker = Path("/usr/local/bin/docker")
    image = os.environ.get(
        "SKRILLER_EGRESS_TEST_IMAGE",
        "skriller-egress-worker-test@sha256:d462f097b7e811570d49ab79aa1895304ce54055507504246bcce344a2b1917c",
    )
    actor, workspace, job = job_fixture(database)
    containers = []
    launched = threading.Event()
    original = runner.bounded_process

    def record(argv, **kwargs):
        if argv[1] == "run":
            containers.append(argv[argv.index("--name") + 1])
            launched.set()
        return original(argv, **kwargs)

    def cancelled():
        with database.tenant(actor, workspace) as session:
            return JobRepository.get(session, job)["state"] == "cancelled"

    monkeypatch.setattr(runner, "bounded_process", record)
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin"}
    with ThreadPoolExecutor(max_workers=1) as executor:
        task = executor.submit(
            IsolatedRunner(image=image, docker=docker).run,
            "youtube_metadata",
            "https://youtu.be/fixture",
            timeout=20,
            cancel_check=cancelled,
        )
        try:
            assert launched.wait(3)
            readiness_deadline = time.monotonic() + 8
            while time.monotonic() < readiness_deadline:
                logs = subprocess.run(
                    [str(docker), "logs", containers[0]],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    env=env,
                    check=False,
                )
                if "parent-ready" in logs.stdout and "descendant-ready" in logs.stdout:
                    break
                if task.done():
                    pytest.fail(f"Fixture failed to start: {task.result().status}")
                time.sleep(0.05)
            else:
                pytest.fail("Fixture parent and descendant readiness was not confirmed")
            started = time.monotonic()
            with database.tenant(actor, workspace) as session:
                cancel(session, job)
            result = task.result(timeout=5)
            elapsed = time.monotonic() - started
            assert result.status == "cancelled", result.stderr
            assert elapsed < 5
            assert "parent-ready" in result.stdout and "descendant-ready" in result.stdout
            inspect = subprocess.run(
                [str(docker), "inspect", containers[0]],
                capture_output=True,
                text=True,
                timeout=2,
                env=env,
                check=False,
            )
            assert inspect.returncode != 0 and "no such" in inspect.stderr.casefold()
        finally:
            if containers:
                cleanup = subprocess.run(
                    [str(docker), "rm", "-f", containers[0]],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=env,
                    check=False,
                )
                assert cleanup.returncode == 0 or "No such container" in cleanup.stderr
