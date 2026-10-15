import hashlib

import pytest

from scripts import provision_tokenizer as tokenizer


def test_setup_refuses_missing_or_tampered_asset_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(tokenizer.urllib.request, "urlopen", lambda *a, **k: pytest.fail("network"))
    with pytest.raises(ValueError, match="Missing"):
        tokenizer.provision(tmp_path)
    (tmp_path / tokenizer.KEY).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="integrity"):
        tokenizer.provision(tmp_path, download=True)
    assert (tmp_path / tokenizer.KEY).read_bytes() == b"tampered"


def test_setup_verifies_read_only_existing_asset(tmp_path, monkeypatch):
    data = b"synthetic tokenizer fixture"
    monkeypatch.setattr(tokenizer, "DIGEST", hashlib.sha256(data).hexdigest())
    target = tmp_path / tokenizer.KEY
    target.write_bytes(data)
    target.chmod(0o444)
    assert tokenizer.provision(tmp_path) == target
    assert target.read_bytes() == data


def test_setup_rejects_cache_symlink(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        tokenizer.provision(alias)
