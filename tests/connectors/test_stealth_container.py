"""Opt-in controlled Chromium test, with no external site or user browser."""

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from skriller.security.runner import IsolatedRunner, bounded_process


def test_real_copied_solver_in_network_none_container():
    image = os.environ.get("SKRILLER_STEALTH_TEST_IMAGE")
    if not image:
        pytest.skip("Requires the reviewed immutable local stealth image")
    IsolatedRunner(image)
    root = Path(__file__).resolve().parents[2]
    name = "skriller-stealth-fixture-" + uuid4().hex
    docker = "/usr/local/bin/docker"
    argv = [
        docker,
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
    ]
    for cap in ("NET_ADMIN", "SETUID", "SETGID", "SETPCAP"):
        argv += ["--cap-add", cap]
    argv += [
        "--security-opt",
        "no-new-privileges:true",
        "--pids-limit",
        "256",
        "--memory",
        "1g",
        "--cpus",
        "1",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=256m",
        "--tmpfs",
        "/dev/shm:rw,nosuid,nodev,size=128m",
        "--mount",
        f"type=bind,source={root}/scripts/probes/stealth_fixture.py,target=/work/probe.py,readonly",
    ]
    for key, value in {
        "HOME": "/tmp",
        "SKRILLER_PROXY_IP": "172.29.0.2",
        "SKRILLER_RUN_UID": "65532",
        "SKRILLER_RUN_GID": "65532",
    }.items():
        argv += ["--env", key + "=" + value]
    argv += ["--entrypoint", "/usr/local/bin/guarded-worker", image, "python", "/work/probe.py"]
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin"}
    try:
        result = bounded_process(argv, cwd=root, env=env, timeout=45, max_output=16384)
    finally:
        cleanup = bounded_process(
            [docker, "rm", "-f", name], cwd=root, env=env, timeout=10, max_output=8192
        )
    assert cleanup.status == "completed" or "No such container" in cleanup.stderr
    assert result.status == "completed", result
    outcome = json.loads(result.stdout)
    assert outcome["cleared_page"] and outcome["persistent_rejected"]
    assert outcome["network"] == "none" and outcome["persistent_seconds"] < 3.6
    print(
        json.dumps(
            {
                "image": image,
                "outer_elapsed_ms": result.elapsed_ms,
                "cleanup_confirmed": True,
                **outcome,
            }
        )
    )
