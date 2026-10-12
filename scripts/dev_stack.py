"""Run the local API, research worker and web app together in the foreground.

PostgreSQL/RabbitMQ must already be running. Ctrl-C stops only these child
processes; existing services or another process using the ports are never killed.
"""

import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    pnpm = shutil.which("pnpm")
    python = ROOT / ".venv/bin/python"
    if not pnpm or not python.exists():
        raise SystemExit("Install the locked Python and web dependencies first; see README.md.")
    for port in (8000, 3000):
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
        (
            [pnpm, "exec", "next", "dev", "--hostname", "127.0.0.1", "--port", "3000"],
            ROOT / "apps/web",
        ),
    ]
    children: list[subprocess.Popen] = []

    def stop(_signal, _frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, stop)
    try:
        for command, directory in commands:
            children.append(subprocess.Popen(command, cwd=directory, start_new_session=True))
        print("Skriller: http://localhost:3000; API: http://localhost:8000", flush=True)
        print("Keep this terminal open. Ctrl-C stops the API, worker and web app.", flush=True)
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
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=5)


if __name__ == "__main__":
    main()
