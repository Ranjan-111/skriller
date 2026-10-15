import hashlib

import pytest

from scripts.provision_cleanup_assets import compatible_abi, provision


def test_stable_abi_wheel_compatibility_is_bounded_to_pinned_python():
    assert compatible_abi("pkg-1-cp37-abi3-manylinux2014_aarch64.whl")
    assert not compatible_abi("pkg-1-cp313-abi3-manylinux2014_aarch64.whl")
    assert not compatible_abi("pkg-1-cp37-cp37-manylinux2014_aarch64.whl")


def test_provision_prefers_universal_wheel_and_verifies_locked_bytes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    content = b"synthetic wheel bytes"
    digest = hashlib.sha256(content).hexdigest()
    name = "example-1-py3-none-any.whl"
    (tmp_path / "uv.lock").write_text(
        f"""[[package]]
name = "example"
version = "1"
wheels = [
    {{url = "https://files.pythonhosted.org/packages/{name}", hash = "sha256:{digest}", size = {len(content)}}},
    {{url = "https://files.pythonhosted.org/packages/example-1-cp312-cp312-manylinux2014_aarch64.whl", hash = "sha256:unknown", size = 1}},
]
"""
    )
    destination = tmp_path / "wheels"
    destination.mkdir()
    (destination / name).write_bytes(content)
    assert provision(destination, "aarch64", package_names={"example"}) == 1
    assert (destination / "SHA256SUMS").read_text() == f"{digest}  {name}\n"
    (destination / name).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="integrity"):
        provision(destination, "aarch64", package_names={"example"})
