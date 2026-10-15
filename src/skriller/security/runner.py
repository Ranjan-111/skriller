"""Fixed backend commands inside a filesystem/network-isolated worker image."""

from __future__ import annotations

import os
import re
import selectors
import signal
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from agent_reach.utils.paths import make_private_dir
from agent_reach.utils.process import utf8_subprocess_env
from agent_reach.utils.text import scrub_url_credentials
from agent_reach.utils.url import normalize_public_http_url


@dataclass(frozen=True)
class RunResult:
    status: str
    returncode: int | None
    stdout: str
    stderr: str
    elapsed_ms: int


def _control_status(cancel_check: Callable[[], bool] | None) -> str | None:
    if cancel_check is None:
        return None
    try:
        cancelled = cancel_check()
        if not isinstance(cancelled, bool):
            return "control_unavailable"
        return "cancelled" if cancelled else None
    except Exception:  # noqa: BLE001 - fail closed without exposing control credentials
        return "control_unavailable"


def bounded_process(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float = 30,
    max_output: int = 1024 * 1024,
    cancel_check: Callable[[], bool] | None = None,
) -> RunResult:
    """Drain both pipes while enforcing a combined byte/time budget and group kill."""
    if timeout <= 0 or max_output < 1:
        raise ValueError("Process budgets must be positive")
    started = time.monotonic()
    stopped = _control_status(cancel_check)
    if stopped:
        return RunResult(stopped, None, "", "", round((time.monotonic() - started) * 1000))
    output = {"stdout": bytearray(), "stderr": bytearray()}
    status = "completed"
    total = 0
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            shell=False,
            close_fds=True,
        )
    except OSError:
        return RunResult("unavailable", None, "", "Executable could not be started", 0)
    # Popen's PIPE arguments guarantee these handles; check that invariant
    # explicitly before selector registration rather than assuming optional IO.
    assert process.stdout is not None and process.stderr is not None
    stdout, stderr = process.stdout, process.stderr
    try:
        with selectors.DefaultSelector() as selector:
            for name, stream in (("stdout", stdout), ("stderr", stderr)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map() or process.poll() is None:
                stopped = _control_status(cancel_check)
                if stopped:
                    status = stopped
                    break
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    status = "timeout"
                    break
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fd, min(65536, max_output - total + 1))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    accepted = chunk[: max_output - total]
                    output[key.data].extend(accepted)
                    total += len(chunk)
                    if total > max_output:
                        status = "output_limit"
                        break
                if status != "completed":
                    break
    finally:
        # Kill residual descendants even if the parent exited before pipe EOF.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
        stdout.close()
        stderr.close()
    if status == "completed" and process.returncode != 0:
        status = "failed"
    return RunResult(
        status,
        process.returncode,
        scrub_url_credentials(output["stdout"].decode("utf-8", errors="replace")),
        scrub_url_credentials(output["stderr"].decode("utf-8", errors="replace")),
        round((time.monotonic() - started) * 1000),
    )


def reviewed_command(operation: str, target: str) -> list[str]:
    if operation in {"youtube_metadata", "youtube_read"}:
        from agent_reach.utils.url import host_matches

        url = normalize_public_http_url(target)
        if not host_matches(url, "youtube.com", "youtu.be"):
            raise ValueError("YouTube metadata requires a YouTube URL")
        if operation == "youtube_read":
            return ["python", "-m", "skriller.connectors.youtube_worker", url]
        return [
            "/usr/local/bin/yt-dlp",
            "--ignore-config",
            "--no-playlist",
            "--skip-download",
            "--dump-single-json",
            "--socket-timeout",
            "10",
            "--",
            url,
        ]
    raise ValueError("Unsupported backend operation; shell and write commands are forbidden")


@dataclass(frozen=True)
class IsolatedRunner:
    image: str
    docker: Path = Path("/usr/local/bin/docker")
    network: str = "skriller_egress_workers"
    proxy_ip: str = "172.29.0.2"

    def __post_init__(self):
        if not re.fullmatch(r"(?:[a-zA-Z0-9._/:-]+@)?sha256:[a-f0-9]{64}", self.image):
            raise ValueError("Worker image requires an immutable registry digest or local image ID")
        if self.network != "skriller_egress_workers" or self.proxy_ip != "172.29.0.2":
            raise ValueError("Runner requires the reviewed guarded network topology")
        if not self.docker.is_absolute():
            raise ValueError("Docker executable must use an administrator-owned absolute path")

    def run(
        self,
        operation: str,
        target: str,
        *,
        timeout: float = 60,
        max_output: int = 1024 * 1024,
        cancel_check: Callable[[], bool] | None = None,
    ) -> RunResult:
        if not 0 < timeout <= 180 or not 0 < max_output <= 10 * 1024 * 1024:
            raise ValueError("Backend budget exceeds the execution boundary")
        command = reviewed_command(operation, target)
        started = time.monotonic()
        stopped = _control_status(cancel_check)
        if stopped:
            return RunResult(stopped, None, "", "", round((time.monotonic() - started) * 1000))
        container = "skriller-backend-" + uuid.uuid4().hex
        # Pass a non-empty allowlist into the reused helper so it cannot fall
        # back to os.environ. No host token, proxy or credential variables leak.
        env = utf8_subprocess_env({"PATH": "/usr/local/bin:/usr/bin:/bin"})
        # Resolve the trusted OS temp root first (macOS /var is a symlink).
        with tempfile.TemporaryDirectory(
            prefix="skriller-backend-", dir=Path(tempfile.gettempdir()).resolve()
        ) as directory:
            workspace = make_private_dir(directory)
            argv = [
                str(self.docker),
                "run",
                "--rm",
                "--name",
                container,
                "--network",
                self.network,
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
                "128",
                "--memory",
                "512m",
                "--cpus",
                "1",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,size=128m",
                "--mount",
                f"type=bind,source={workspace},target=/work",
                "--workdir",
                "/work",
                "--env",
                "HOME=/work",
                "--env",
                "XDG_CONFIG_HOME=/work/config",
                "--env",
                "PYTHONUTF8=1",
                "--env",
                "PYTHONIOENCODING=utf-8",
                "--env",
                f"SKRILLER_RUN_UID={os.getuid() or 65532}",
                "--env",
                f"SKRILLER_RUN_GID={os.getgid() or 65532}",
                "--env",
                f"SKRILLER_PROXY_IP={self.proxy_ip}",
                "--env",
                f"HTTPS_PROXY=http://{self.proxy_ip}:8080",
                "--env",
                f"HTTP_PROXY=http://{self.proxy_ip}:8080",
                "--entrypoint",
                "/usr/local/bin/guarded-worker",
                self.image,
                *command,
            ]
            try:
                result = bounded_process(
                    argv,
                    cwd=workspace,
                    env=env,
                    timeout=timeout,
                    max_output=max_output,
                    cancel_check=cancel_check,
                )
            finally:
                # Killing the docker client alone does not terminate a daemon-
                # owned container: explicitly remove this task's unique container.
                cleanup = bounded_process(
                    [str(self.docker), "rm", "-f", container],
                    cwd=workspace,
                    env=env,
                    timeout=10,
                    max_output=8192,
                )
            if cleanup.status != "completed" and "No such container" not in cleanup.stderr:
                return RunResult(
                    "cleanup_failed",
                    result.returncode,
                    result.stdout,
                    "Isolated worker cleanup could not be confirmed",
                    round((time.monotonic() - started) * 1000),
                )
            return RunResult(
                result.status,
                result.returncode,
                result.stdout,
                result.stderr,
                round((time.monotonic() - started) * 1000),
            )
