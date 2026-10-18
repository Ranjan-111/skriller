"""Installed acquired LinkedIn capture with synthetic data and no network."""

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from skriller.security.runner import IsolatedRunner, bounded_process


def test_installed_linkedin_worker_inside_guarded_container():
    image = os.environ.get("SKRILLER_LINKEDIN_TEST_IMAGE")
    if not image:
        pytest.skip("Requires the built immutable LinkedIn worker image")
    IsolatedRunner(image)
    root = Path(__file__).resolve().parents[2]
    name = "skriller-linkedin-fixture-" + uuid4().hex
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
            "256",
            "--memory",
            "1g",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=256m",
            "--mount",
            f"type=bind,source={root}/scripts/probes/linkedin_fixture.py,target=/work/probe.py,readonly",
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
        result = bounded_process(argv, cwd=root, env=env, timeout=60, max_output=16384)
    finally:
        cleanup = bounded_process(
            [docker, "rm", "-f", name], cwd=root, env=env, timeout=10, max_output=8192
        )
    assert cleanup.status == "completed" or "No such container" in cleanup.stderr
    assert result.status == "completed", result
    report = json.loads(result.stdout)
    assert report["installed_capture_pipeline"] and report["search_reference_verified"]
    assert report["operations_checked"] == ["search_people", "search_posts"]
    assert report["failure_sanitization_verified"]
    assert report["resource_operations_checked"] == ["read_profile", "read_company", "read_post"]
    assert report["network"] == "none" and report["source_live_verified"] is False
    print(json.dumps({"image": image, "cleanup_confirmed": True, **report}))
