"""Fixed backend commands inside a filesystem/network-isolated worker image."""

from __future__ import annotations

import json
import os
import re
import selectors
import signal
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from skriller.connections.store import RunnerSecrets

from agent_reach.utils.paths import make_private_dir
from agent_reach.utils.process import utf8_subprocess_env
from agent_reach.utils.text import scrub_url_credentials
from agent_reach.utils.url import normalize_public_http_url

SOCIAL_OPERATIONS = {"instagram_search", "instagram_profile", "facebook_search", "facebook_profile"}
BROWSER_OPERATIONS = {"linkedin_search", "linkedin_resource_read", *SOCIAL_OPERATIONS}


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
    if operation in SOCIAL_OPERATIONS:
        from skriller.connectors.social_worker import OPERATIONS

        social_request = OPERATIONS[operation].model_validate_json(target)
        return [
            "python",
            "-m",
            "skriller.connectors.social_worker",
            operation,
            social_request.model_dump_json(),
        ]
    if operation in {"linkedin_search", "linkedin_resource_read"}:
        from skriller.connectors.linkedin_discovery import LinkedInSearch
        from skriller.connectors.linkedin_read import LinkedInRead

        linkedin_request = (
            LinkedInRead.model_validate_json(target)
            if operation == "linkedin_resource_read"
            else LinkedInSearch.model_validate_json(target)
        )
        return [
            "python",
            "-m",
            "skriller.connectors.linkedin_worker",
            linkedin_request.model_dump_json(),
        ]
    if operation in {"reddit_oauth_search", "reddit_oauth_read"}:
        from skriller.connectors.reddit_request import RedditRead, RedditSearch

        reddit_request = (
            RedditRead.model_validate_json(target)
            if operation == "reddit_oauth_read"
            else RedditSearch.model_validate_json(target)
        )
        return [
            "python",
            "-m",
            "skriller.connectors.reddit_worker",
            reddit_request.model_dump_json(),
        ]
    if operation == "x_read":
        # The worker accepts only a serialized, bounded search request. It
        # chooses the one fixed official endpoint; callers cannot supply URLs.
        from skriller.connectors.x_discovery import XSearch

        try:
            request = XSearch.model_validate_json(target)
        except Exception as exc:
            raise ValueError("X read requires a bounded search request") from exc
        return ["python", "-m", "skriller.connectors.x_worker", request.model_dump_json()]
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
        credential_material: RunnerSecrets | None = None,
    ) -> RunResult:
        if not 0 < timeout <= 180 or not 0 < max_output <= 10 * 1024 * 1024:
            raise ValueError("Backend budget exceeds the execution boundary")
        command = reviewed_command(operation, target)
        if credential_material is not None:
            from skriller.connections.store import RUNNERS, RunnerSecrets

            if (
                not isinstance(credential_material, RunnerSecrets)
                or credential_material.runner != operation
                or operation not in RUNNERS
                or not credential_material.environment
                or not set(credential_material.environment) <= set(RUNNERS[operation][1].values())
            ):
                raise ValueError("Credential material must match its fixed source operation")
        started = time.monotonic()
        stopped = _control_status(cancel_check)
        if stopped:
            return RunResult(stopped, None, "", "", round((time.monotonic() - started) * 1000))
        container = "skriller-backend-" + uuid.uuid4().hex
        # Pass a non-empty allowlist into the reused helper so it cannot fall
        # back to os.environ. No host token, proxy or credential variables leak.
        env = utf8_subprocess_env({"PATH": "/usr/local/bin:/usr/bin:/bin"})
        # Resolve the trusted OS temp root first (macOS /var is a symlink).
        with ExitStack() as resources:
            directory = resources.enter_context(
                tempfile.TemporaryDirectory(
                    prefix="skriller-backend-", dir=Path(tempfile.gettempdir()).resolve()
                )
            )
            workspace = make_private_dir(directory)
            credential_options: list[str] = []
            if credential_material is not None:
                secret_directory = resources.enter_context(
                    tempfile.TemporaryDirectory(
                        prefix="skriller-credential-", dir=Path(tempfile.gettempdir()).resolve()
                    )
                )
                path = make_private_dir(secret_directory) / "credentials.json"
                content = json.dumps(
                    {
                        "schema_version": 1,
                        "runner": operation,
                        "connection_ref": str(credential_material.connection_ref),
                        "environment": credential_material.injection(),
                    }
                ).encode()
                if len(content) > 65536:
                    raise ValueError("Credential delivery exceeds its byte bound")
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                credential_options = [
                    "--log-driver",
                    "none",
                    "--mount",
                    f"type=bind,source={path},target=/run/skriller-credentials.json,readonly",
                ]
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
                "256" if operation in BROWSER_OPERATIONS else "128",
                "--memory",
                "1g" if operation in BROWSER_OPERATIONS else "512m",
                "--cpus",
                "1",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,size=256m"
                if operation in BROWSER_OPERATIONS
                else "/tmp:rw,nosuid,nodev,size=128m",
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
                *(["--env", "SKRILLER_X_WORKER=isolated"] if operation == "x_read" else []),
                *(
                    ["--env", "SKRILLER_LINKEDIN_WORKER=isolated"]
                    if operation in {"linkedin_search", "linkedin_resource_read"}
                    else []
                ),
                *(
                    ["--env", "SKRILLER_SOCIAL_WORKER=isolated"]
                    if operation in SOCIAL_OPERATIONS
                    else []
                ),
                *(
                    ["--env", "SKRILLER_REDDIT_WORKER=isolated"]
                    if operation in {"reddit_oauth_search", "reddit_oauth_read"}
                    else []
                ),
                "--env",
                f"HTTPS_PROXY=http://{self.proxy_ip}:8080",
                "--env",
                f"HTTP_PROXY=http://{self.proxy_ip}:8080",
                "--entrypoint",
                "/usr/local/bin/guarded-worker",
                *credential_options,
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
            if credential_material is not None:
                from skriller.connections.store import redact_output

                result = RunResult(
                    result.status,
                    result.returncode,
                    redact_output(result.stdout, credential_material),
                    # Raw backend error logs do not belong in a credential-bearing result.
                    "" if result.status == "completed" else "Source worker did not complete",
                    result.elapsed_ms,
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
