"""Cold container boot, packaged copied token assets and no runtime network."""

import json
import os
import re
import subprocess
from uuid import uuid4

import pytest


@pytest.mark.integration_db
@pytest.mark.parametrize("mode", [[], ["--missing-assets"]])
def test_packaged_cleanup_offline(mode):
    image = os.environ.get("SKRILLER_CLEANUP_TEST_IMAGE")
    if not image:
        pytest.skip("Requires explicit installed immutable cleanup image")
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", image)
    container = "skriller-cleanup-test-" + uuid4().hex
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                container,
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--user",
                "65534:65534",
                "--pids-limit",
                "32",
                "--memory",
                "256m",
                "--cpus",
                "1",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=32m",
                "--entrypoint",
                "python",
                image,
                "/app/offline_cleanup.py",
                *mode,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr[-2000:]
        report = json.loads(result.stdout)
        assert report["status"] == "passed"
        if mode:
            assert report["missing_assets"] == "typed_unavailable"
        else:
            assert report["runtime_network"] == "denied"
            assert report["preserved_evidence"] > 0 and report["copied_chunks"] > 0
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container], capture_output=True, timeout=5, check=False
        )
