"""Concrete digest-pinned public browser container; no host browser fallback."""

import base64
import json
import os
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from time import monotonic

from agent_reach.utils.paths import make_private_dir
from agent_reach.utils.process import utf8_subprocess_env

from skriller.connectors.browser import BrowserRequest, BrowserResult
from skriller.connectors.fetch import _failure, _public_url
from skriller.security.runner import IsolatedRunner, _control_status, bounded_process


@dataclass(frozen=True)
class ConcreteBrowserExecutor:
    image: str
    docker: Path = Path("/usr/local/bin/docker")

    def __post_init__(self):
        IsolatedRunner(self.image, docker=self.docker)

    def execute(
        self, request: BrowserRequest, *, cancel_check: Callable[[], bool] | None = None
    ) -> BrowserResult:
        if not isinstance(request, BrowserRequest):
            raise TypeError("Typed browser request required")
        stopped = _control_status(cancel_check)
        if stopped:
            raise _failure(
                "cancelled" if stopped == "cancelled" else "source_unavailable",
                "Browser dispatch was stopped",
            )
        container = "skriller-browser-" + uuid.uuid4().hex
        env = utf8_subprocess_env({"PATH": "/usr/local/bin:/usr/bin:/bin"})
        with tempfile.TemporaryDirectory(
            prefix="skriller-browser-request-", dir=Path(tempfile.gettempdir()).resolve()
        ) as directory:
            workspace = make_private_dir(directory)
            payload = json.dumps(asdict(request), allow_nan=False).encode()
            if len(payload) > 16384:
                raise ValueError("Browser request exceeds wire bound")
            path = workspace / "request.json"
            path.write_bytes(payload)
            path.chmod(0o600)
            argv = [
                str(self.docker),
                "run",
                "--rm",
                "--name",
                container,
                "--network",
                "skriller_egress_workers",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--cap-add",
                "NET_ADMIN",
                "--cap-add",
                "SETUID",
                "--cap-add",
                "SETGID",
                "--cap-add",
                "SETPCAP",
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
                f"type=bind,source={workspace},target=/work,readonly",
                "--workdir",
                "/work",
            ]
            for name, value in {
                "HOME": "/tmp",
                "XDG_CONFIG_HOME": "/tmp/config",
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
                "SKRILLER_BROWSER_WORKER": "isolated",
                "SKRILLER_RUN_UID": str(os.getuid() or 65532),
                "SKRILLER_RUN_GID": str(os.getgid() or 65532),
                "SKRILLER_PROXY_IP": "172.29.0.2",
                "HTTP_PROXY": "http://172.29.0.2:8080",
                "HTTPS_PROXY": "http://172.29.0.2:8080",
            }.items():
                argv.extend(["--env", f"{name}={value}"])
            argv.extend(
                [
                    "--entrypoint",
                    "/usr/local/bin/guarded-worker",
                    self.image,
                    "python",
                    "-m",
                    "skriller.connectors.browser_worker",
                    "/work/request.json",
                ]
            )
            started = monotonic()
            try:
                outcome = bounded_process(
                    argv,
                    cwd=workspace,
                    env=env,
                    timeout=request.timeout_seconds,
                    max_output=3 * 1024 * 1024,
                    cancel_check=cancel_check,
                )
            finally:
                cleanup = bounded_process(
                    [str(self.docker), "rm", "-f", container],
                    cwd=workspace,
                    env=env,
                    timeout=10,
                    max_output=8192,
                )
            if cleanup.status != "completed" and "No such container" not in cleanup.stderr:
                raise _failure("source_unavailable", "Browser container cleanup was not confirmed")
            if outcome.status != "completed":
                if outcome.status == "failed":
                    try:
                        error = json.loads(outcome.stdout)
                    except (ValueError, TypeError):
                        error = None
                    if error == {"error": "deadline_exceeded"}:
                        raise _failure("deadline_exceeded", "Copied solver reached its deadline")
                code = {
                    "cancelled": "cancelled",
                    "timeout": "deadline_exceeded",
                    "output_limit": "budget_exhausted",
                }.get(outcome.status, "source_unavailable")
                raise _failure(code, "Isolated browser execution did not complete")
            try:
                data = json.loads(outcome.stdout)
                if set(data) != {
                    "content_base64",
                    "final_url",
                    "status",
                    "request_count",
                    "elapsed_seconds",
                }:
                    raise ValueError("Invalid response fields")
                content = base64.b64decode(data["content_base64"], validate=True)
                if (
                    len(content) > request.max_body_bytes
                    or data["request_count"] > request.max_requests
                ):
                    raise ValueError("Worker response exceeds request bounds")
                if not isinstance(data["final_url"], str):
                    raise TypeError("Typed public final URL required")
                result = BrowserResult(
                    content,
                    _public_url(data["final_url"]),
                    data["status"],
                    data["request_count"],
                    monotonic() - started,
                )
            except Exception:  # noqa: BLE001 - redact untrusted child wire/SDK errors
                raise _failure(
                    "source_unavailable", "Browser worker returned an invalid response"
                ) from None
            stopped = _control_status(cancel_check)
            if stopped:
                raise _failure(
                    "cancelled" if stopped == "cancelled" else "source_unavailable",
                    "Browser result arrived after execution stopped",
                )
            return result
