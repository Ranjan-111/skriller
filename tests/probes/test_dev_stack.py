"""Local launcher uses installed tools and never requires a global pnpm wrapper."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "dev_stack", Path(__file__).parents[2] / "scripts/dev_stack.py"
)
dev_stack = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(dev_stack)


def test_launcher_requires_installed_next_before_loading_local_configuration(monkeypatch, tmp_path):
    monkeypatch.setattr(dev_stack, "ROOT", tmp_path)
    monkeypatch.setattr(
        dev_stack.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None
    )
    monkeypatch.setattr(
        dev_stack,
        "Settings",
        lambda **_: pytest.fail("must not load config without installed tools"),
    )
    with pytest.raises(SystemExit, match="locked Python and web dependencies"):
        dev_stack.main([])


@pytest.mark.parametrize("discovery_only", [False, True])
def test_launcher_runs_project_next_without_global_pnpm(monkeypatch, tmp_path, discovery_only):
    python = tmp_path / ".venv/bin/python"
    next_cli = tmp_path / "apps/web/node_modules/next/dist/bin/next"
    for path in (python, next_cli):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    monkeypatch.setattr(dev_stack, "ROOT", tmp_path)
    monkeypatch.setattr(
        dev_stack.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None
    )
    monkeypatch.setattr(
        dev_stack,
        "Settings",
        lambda **_: type("Config", (), {"public_collection_proxy_url": None})(),
    )

    class Probe:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def connect_ex(self, _):
            return 1

    monkeypatch.setattr(dev_stack.socket, "socket", lambda: Probe())
    commands = []

    class Child:
        def __init__(self, argv, **kwargs):
            self.pid = len(commands) + 100
            commands.append((argv, kwargs))

        def poll(self):
            return None

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(dev_stack.subprocess, "Popen", Child)
    monkeypatch.setattr(
        dev_stack.time, "sleep", lambda _: (_ for _ in ()).throw(KeyboardInterrupt())
    )
    # Reproduce an exit between poll and killpg; shutdown must still visit all children.
    killed = []

    def vanished(pid, _):
        killed.append(pid)
        raise ProcessLookupError

    monkeypatch.setattr(dev_stack.os, "killpg", vanished)
    dev_stack.main(["--discovery-only"] if discovery_only else [])
    assert commands[-1][0] == [
        "/usr/bin/node",
        str(next_cli),
        "dev",
        "--hostname",
        "127.0.0.1",
        "--port",
        "3000",
    ]
    assert all(row[1]["start_new_session"] for row in commands)
    assert len(killed) == len(commands) == 4
    if discovery_only:
        for _, options in commands:
            env = options["env"]
            assert env["SKRILLER_ENABLE_AI_PLANNING"] == "false"
            assert env["SKRILLER_ENABLE_PAGE_EXTRACTION"] == "false"
            assert env["SKRILLER_ENABLE_DYNAMIC_COLLECTION"] == "false"
            assert env["SKRILLER_PUBLIC_LINKEDIN_IMAGE"] == ""
            assert env["SKRILLER_PUBLIC_REDDIT_IMAGE"] == ""
            assert env["SKRILLER_PUBLIC_COLLECTION_PROXY_URL"] == ""
