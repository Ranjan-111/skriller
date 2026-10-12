"""Verify lock provenance and selected copied engine import capabilities."""

import importlib
import importlib.metadata
import json
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINES = {
    "scrapling": ("scrapling", "third_party/scrapling"),
    "agent-reach": ("agent_reach", "third_party/agent-reach"),
    "scrapegraphai": ("scrapegraphai", "third_party/scrapegraph-ai"),
}


class DependencyLockTests(unittest.TestCase):
    def test_lock_pins_copied_engines_and_hashes_registry_artifacts(self):
        lock = tomllib.loads((ROOT / "uv.lock").read_text())
        packages = {package["name"]: package for package in lock["package"]}
        self.assertEqual(lock["requires-python"], "==3.12.*")
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())
        for distribution, (_, relative) in ENGINES.items():
            with self.subTest(distribution=distribution):
                self.assertEqual(packages[distribution]["source"], {"editable": relative})
                self.assertEqual(
                    project["tool"]["uv"]["sources"][distribution],
                    {"path": relative, "editable": True},
                )
                upstream = tomllib.loads((ROOT / relative / "pyproject.toml").read_text())
                self.assertEqual(packages[distribution]["version"], upstream["project"]["version"])
        for package in packages.values():
            if "registry" not in package["source"]:
                continue
            artifacts = package.get("wheels", []) + (
                [package["sdist"]] if "sdist" in package else []
            )
            self.assertTrue(artifacts, package["name"])
            self.assertTrue(
                all(artifact["hash"].startswith("sha256:") for artifact in artifacts),
                package["name"],
            )

    def test_installed_engines_resolve_to_local_sources_with_matching_versions(self):
        lock = tomllib.loads((ROOT / "uv.lock").read_text())
        packages = {package["name"]: package for package in lock["package"]}
        for distribution, (module_name, relative) in ENGINES.items():
            with self.subTest(distribution=distribution):
                module = importlib.import_module(module_name)
                self.assertTrue(Path(module.__file__).resolve().is_relative_to(ROOT / relative))
                installed = importlib.metadata.distribution(distribution)
                self.assertEqual(installed.version, packages[distribution]["version"])
                direct = json.loads(installed.read_text("direct_url.json"))
                self.assertTrue(direct["dir_info"]["editable"])
                self.assertEqual(direct["url"], (ROOT / relative).as_uri())

    def test_selected_entry_points_import_without_live_service_calls(self):
        script = """
from unittest.mock import patch
import socket
with patch.object(socket.socket, 'connect', side_effect=AssertionError('network')):
    from scrapling import Selector
    from scrapling.fetchers import Fetcher, DynamicFetcher, StealthyFetcher
    from agent_reach import AgentReach
    from scrapegraphai.graphs import SmartScraperGraph
    from scrapegraphai.nodes import FetchNode, GenerateAnswerNode
    assert Selector('<p>Acme</p>').css('p::text').get() == 'Acme'
"""
        result = subprocess.run(
            [sys.executable, "-c", script], check=False, cwd=ROOT, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_optional_browser_dependency_has_explicit_diagnostic(self):
        script = """
import importlib.abc
import sys
from scrapegraphai.utils.sys_dynamic_import import dynamic_import
class MissingBrowser(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'playwright' or fullname.startswith('playwright.'):
            raise ModuleNotFoundError('Simulated missing optional playwright', name='playwright')
sys.meta_path.insert(0, MissingBrowser())
try:
    dynamic_import('playwright', 'Browser capability disabled: install locked Playwright dependency')
except ImportError as error:
    assert 'Browser capability disabled' in str(error)
    assert error.__cause__.name == 'playwright'
else:
    raise AssertionError('Missing browser dependency silently replaced')
from scrapegraphai.telemetry.telemetry import is_telemetry_enabled
assert not is_telemetry_enabled()
"""
        result = subprocess.run(
            [sys.executable, "-c", script], check=False, cwd=ROOT, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
