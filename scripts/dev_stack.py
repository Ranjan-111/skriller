"""Run the local API, research worker and web app together in the foreground.

PostgreSQL/RabbitMQ must already be running. Ctrl-C stops only these child
processes; existing services or another process using the ports are never killed.
"""

import argparse
import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

from skriller.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--discovery-only",
        action="store_true",
        help="Run indexed discovery/source downloads without AI planning or direct source reads",
    )
    args = parser.parse_args(argv)
    node = shutil.which("node")
    next_cli = ROOT / "apps/web/node_modules/next/dist/bin/next"
    python = ROOT / ".venv/bin/python"
    if not node or not next_cli.is_file() or not python.exists():
        raise SystemExit("Install the locked Python and web dependencies first; see README.md.")
    overrides = {}
    child_env = os.environ.copy()
    if args.discovery_only:
        overrides = {
            "enable_ai_planning": False,
            "enable_page_extraction": False,
            "enable_dynamic_collection": False,
            "enable_stealth_collection": False,
            "public_collection_proxy_url": None,
            **{
                f"public_{source}_image": None
                for source in (
                    "browser",
                    "youtube",
                    "x",
                    "reddit",
                    "linkedin",
                    "social",
                )
            },
        }
        child_env.update(
            {
                "SKRILLER_" + name.upper(): "false" if value is False else ""
                for name, value in overrides.items()
            }
        )
    settings = Settings(_env_file=ROOT / ".env", **overrides)
    proxy = urlsplit(settings.public_collection_proxy_url or "")
    local_proxy = proxy.hostname in {"127.0.0.1", "localhost"}
    ports = [8000, 3000] + ([proxy.port] if local_proxy else [])
    for port in ports:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise SystemExit(
                    f"Port {port} is already in use. Existing services were left running."
                )
    commands = [
        (
            [
                str(python),
                "-m",
                "uvicorn",
                "skriller.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
                "--no-access-log",
            ],
            ROOT,
        ),
        ([str(python), "-m", "skriller.research.runtime"], ROOT),
        ([str(python), "-m", "skriller.retention_runtime"], ROOT),
        (
            [node, str(next_cli), "dev", "--hostname", "127.0.0.1", "--port", "3000"],
            ROOT / "apps/web",
        ),
    ]
    if local_proxy:
        commands.insert(
            0,
            ([str(python), str(ROOT / "scripts/egress_proxy.py"), "--port", str(proxy.port)], ROOT),
        )
    children: list[subprocess.Popen] = []

    def stop(_signal, _frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, stop)
    try:
        for command, directory in commands:
            children.append(
                subprocess.Popen(
                    command,
                    cwd=directory,
                    env=child_env,
                    start_new_session=True,
                )
            )
        print("Skriller: http://localhost:3000; API: http://localhost:8000", flush=True)
        print("Keep this terminal open. Ctrl-C stops the API, worker and web app.", flush=True)
        if args.discovery_only:
            print(
                "Discovery-only profile: indexed results/source downloads; no confirmed-lead quality claim.",
                flush=True,
            )
        while True:
            for child in children:
                if child.poll() is not None:
                    raise SystemExit("A local service exited; check its output above.")
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, previous)
        for child in children:
            if child.poll() is None:
                # Each child owns a new session, including its own worker/dev-server descendants.
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass  # Child exited after poll; continue stopping the other owned children.
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait(timeout=5)


if __name__ == "__main__":
    main()
