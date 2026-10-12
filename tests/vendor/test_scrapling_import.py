"""Verify the installed copied engine; no network or browser launch is needed."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "third_party" / "scrapling"


def test_scrapling_provenance_and_source_closure():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "provenance.py"), "verify", "scrapling"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads((VENDOR / "PROVENANCE.json").read_text())
    names = {item["path"] for item in manifest["files"]}
    for name in (
        "LICENSE", "pyproject.toml", "scrapling/parser.py",
        "scrapling/fetchers/requests.py", "scrapling/fetchers/chrome.py",
        "scrapling/fetchers/stealth_chrome.py", "tests/parser/test_adaptive.py",
        "tests/parser/test_general.py",
    ):
        assert name in names


@pytest.mark.parametrize("module, symbol", [
    ("scrapling.parser", "Selector"),
    ("scrapling.fetchers.requests", "Fetcher"),
    ("scrapling.fetchers.chrome", "DynamicFetcher"),
    ("scrapling.fetchers.stealth_chrome", "StealthyFetcher"),
])
def test_installed_entry_points_resolve_to_copied_tree(tmp_path, module, symbol):
    # Isolated mode ignores PYTHONPATH and the current directory: this exercises
    # the installed local package rather than accidentally loading reference/.
    code = (
        "import importlib, pathlib; "
        f"m=importlib.import_module({module!r}); "
        f"assert getattr(m, {symbol!r}); "
        "print(pathlib.Path(m.__file__).resolve())"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code], cwd=tmp_path,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert Path(result.stdout.strip()).is_relative_to(VENDOR)
