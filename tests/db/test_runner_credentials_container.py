"""Installed guarded runtime, synthetic encrypted account and no platform IO."""

import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from test_connection_execution import prepared

from skriller.connections.execution import run_connected
from skriller.security import runner

pytestmark = pytest.mark.integration_db


@pytest.mark.parametrize("revoke", [False, True])
def test_installed_worker_private_delivery_inspection_redaction_and_revocation(
    database, monkeypatch, revoke
):
    if os.environ.get("SKRILLER_EGRESS_CONTAINER_TESTS") != "1":
        pytest.skip("Requires existing immutable guarded worker and healthy Docker")
    store, actor, workspace, context = prepared(database)
    image = os.environ["SKRILLER_EGRESS_TEST_IMAGE"]
    code = (
        "import json,pathlib,time; "
        "p=pathlib.Path('/run/skriller-credentials.json'); "
        "d=json.loads(p.read_bytes()); "
        "assert d['runner']=='linkedin_read'; "
        "print(d['environment']['LINKEDIN_SESSION_COOKIE'],flush=True); "
        "pathlib.Path('/work/ready').write_text('ready'); "
        "deadline=time.monotonic()+20\n"
        "while not pathlib.Path('/work/release').exists() and time.monotonic()<deadline: time.sleep(.05)\n"
    )
    monkeypatch.setattr(runner, "reviewed_command", lambda *_: ["python", "-c", code])
    original = runner.bounded_process
    launched = {}

    def record(argv, **kwargs):
        if argv[1] == "run":
            launched["container"] = argv[argv.index("--name") + 1]
            launched["workspace"] = kwargs["cwd"]
            mount = next(item for item in argv if "target=/run/skriller-credentials.json" in item)
            launched["secret"] = Path(mount.split("source=", 1)[1].split(",", 1)[0])
        return original(argv, **kwargs)

    monkeypatch.setattr(runner, "bounded_process", record)
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(
            run_connected,
            database,
            store,
            context,
            runner.IsolatedRunner(image),
            "linkedin_read",
            "fixture",
            timeout=25,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if launched.get("workspace") and (launched["workspace"] / "ready").exists():
                break
            if task.done():
                pytest.fail(f"Installed fixture failed before readiness: {task.result().status}")
            time.sleep(0.05)
        else:
            pytest.fail("Installed credential fixture did not become ready")
        inspection = subprocess.run(
            ["/usr/local/bin/docker", "inspect", launched["container"]],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        assert "fixture-session-token" not in inspection.stdout
        metadata = json.loads(inspection.stdout)[0]
        assert metadata["HostConfig"]["LogConfig"]["Type"] == "none"
        mount = next(
            item
            for item in metadata["Mounts"]
            if item["Destination"] == "/run/skriller-credentials.json"
        )
        assert mount["RW"] is False
        started = time.monotonic()
        if revoke:
            with database.tenant(actor, workspace) as session:
                store.revoke(session, context.connection_ref)
        else:
            (launched["workspace"] / "release").write_text("release")
        result = task.result(timeout=5)
        assert time.monotonic() - started < 5
        assert result.status == ("needs_connection" if revoke else "completed")
        assert "fixture-session-token" not in result.stdout + result.stderr
        assert not launched["secret"].parent.exists()
        assert not launched["workspace"].exists()
        inspection = subprocess.run(
            ["/usr/local/bin/docker", "inspect", launched["container"]],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        assert inspection.returncode != 0 and "no such" in inspection.stderr.casefold()
