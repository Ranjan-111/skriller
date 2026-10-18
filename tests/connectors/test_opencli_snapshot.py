"""Imported social backend source integrity; never start its CLI or host bridge."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from skriller.connectors.registry import ConnectorRegistry

ROOT = Path(__file__).parents[2]
SNAPSHOT = ROOT / "third_party/external/opencli"


def test_product_read_subset_keeps_provenance_and_excludes_write_modules():
    subset = ROOT / "src/skriller/_vendor/opencli"
    provenance = json.loads((subset / "PROVENANCE.json").read_text())
    assert provenance["commit"] == "e6174a952c763a836a9bb0dd2f097d2962b3876b"
    assert "Apache License" in (subset / "LICENSE").read_text()
    assert len(provenance["files"]) == 5
    assert {path.relative_to(subset).as_posix() for path in subset.rglob("*.js")} == set(
        provenance["files"]
    )
    for name, record in provenance["files"].items():
        assert hashlib.sha256((SNAPSHOT / name).read_bytes()).hexdigest() == record["source_sha256"]
        assert hashlib.sha256((subset / name).read_bytes()).hexdigest() == record["adapted_sha256"]
        if name.startswith("clis/facebook/") or name.endswith("read-response.js"):
            assert record["source_sha256"] == record["adapted_sha256"]


def test_opencli_snapshot_keeps_license_and_all_recorded_source_hashes():
    manifest = json.loads((SNAPSHOT / "SOURCE_MANIFEST.json").read_text())
    assert manifest["repository"] == "https://github.com/jackwener/OpenCLI"
    assert manifest["commit"] == "e6174a952c763a836a9bb0dd2f097d2962b3876b"
    assert len(manifest["files"]) == 2343
    assert "Apache License" in (SNAPSHOT / "LICENSE").read_text()
    for record in manifest["files"]:
        path = SNAPSHOT / record["path"]
        assert path.resolve().is_relative_to(SNAPSHOT.resolve())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


@pytest.mark.parametrize(
    "source,domain", [("instagram", "instagram.com"), ("facebook", "facebook.com")]
)
def test_source_snapshot_does_not_activate_platform_or_probe_host_accounts(source, domain):
    registry = ConnectorRegistry(uuid4())
    channel = registry.channel(source)
    assert channel.can_handle(f"https://www.{domain}/synthetic/")
    assert not channel.can_handle(f"https://{domain}.evil.example/synthetic/")
    for operation in ("discover", "read"):
        capability = registry.capability(source, operation)
        assert capability.engineering_status == "planned"
        assert capability.operational_status == "needs_connection"
    for operation in ("profile", "search"):
        code = (SNAPSHOT / "clis" / source / f"{operation}.js").read_text()
        assert "access: 'read'" in code
        assert "browser: true" in code or "pipeline:" in code
