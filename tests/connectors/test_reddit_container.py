"""Installed Reddit worker pipeline with synthetic data and no network."""

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from skriller.security.runner import IsolatedRunner, bounded_process


def test_installed_reddit_worker_inside_guarded_container():
    image = os.environ.get("SKRILLER_REDDIT_TEST_IMAGE")
    if not image:
        pytest.skip("Requires the built immutable Reddit worker image")
    IsolatedRunner(image)
    root = Path(__file__).resolve().parents[2]
    name = "skriller-reddit-fixture-" + uuid4().hex
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
        argv.extend(["--cap-add", cap])
    argv.extend(
        [
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            "64",
            "--memory",
            "256m",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=32m",
            "--mount",
            f"type=bind,source={root}/scripts/probes/reddit_fixture.py,target=/work/probe.py,readonly",
        ]
    )
    for key, value in {
        "HOME": "/tmp",
        "SKRILLER_PROXY_IP": "172.29.0.2",
        "SKRILLER_RUN_UID": "65532",
        "SKRILLER_RUN_GID": "65532",
    }.items():
        argv.extend(["--env", f"{key}={value}"])
    argv.extend([image, "python", "/work/probe.py"])
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin"}
    try:
        result = bounded_process(argv, cwd=root, env=env, timeout=30, max_output=16384)
    finally:
        cleanup = bounded_process(
            [docker, "rm", "-f", name], cwd=root, env=env, timeout=10, max_output=8192
        )
    assert cleanup.status == "completed" or "No such container" in cleanup.stderr
    assert result.status == "completed", result
    report = json.loads(result.stdout)
    assert report["actual_worker_pipeline"] and report["post_citation_verified"]
    assert report["thread_read_verified"]
    assert report["network"] == "none" and report["source_live_verified"] is False
    print(json.dumps({"image": image, "cleanup_confirmed": True, **report}))
