import os

import pytest

from skriller.connections.keys import Keyring, KeyUnavailable
from skriller.connections.store import SecretPayload, redact_output


def test_explicit_private_keyfile_roundtrip_and_missing(tmp_path):
    target = tmp_path / "private" / "keys.json"
    created = Keyring.create_file(target)
    loaded = Keyring.load(target)
    assert created.keys == loaded.keys
    assert loaded.active == "v1"
    assert os.stat(target).st_mode & 0o777 == 0o600
    assert os.stat(target.parent).st_mode & 0o777 == 0o700
    assert "keys=" not in repr(loaded)
    with pytest.raises(KeyUnavailable):
        Keyring.load(None)
    with pytest.raises(KeyUnavailable):
        Keyring.load(tmp_path / "missing")
    with pytest.raises(ValueError):
        Keyring.create_file(target)


def test_symlink_insecure_mode_and_malformed_key_denied(tmp_path):
    target = tmp_path / "private" / "keys.json"
    Keyring.create_file(target)
    linked = tmp_path / "link.json"
    linked.symlink_to(target)
    with pytest.raises(KeyUnavailable):
        Keyring.load(linked)
    target.chmod(0o644)
    with pytest.raises(KeyUnavailable):
        Keyring.load(target)
    target.chmod(0o600)
    target.write_text("not a key fixture")
    with pytest.raises(KeyUnavailable) as exc:
        Keyring.load(target)
    assert "not a key fixture" not in str(exc.value)


def test_secret_repr_validation_errors_and_url_cookie_redaction():
    payload = SecretPayload(credentials={"session_cookie": "fixture-hidden-cookie"})
    assert "fixture-hidden-cookie" not in repr(payload)
    with pytest.raises(ValueError) as exc:
        SecretPayload(credentials={"invalid": "fixture-hidden-cookie"})
    assert "fixture-hidden-cookie" not in str(exc.value)
    text = redact_output(
        "https://u:p@host/path?api_key=hidden\nCookie: hidden\nAuthorization: Bearer hidden"
    )
    assert "hidden" not in text and "u:p" not in text


def test_concurrent_initialization_never_replaces_keyring(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    target = tmp_path / "private" / "keys.json"

    def create_once(_):
        try:
            return Keyring.create_file(target)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create_once, range(2)))
    successful = [result for result in results if result is not None]
    assert len(successful) == 1
    assert Keyring.load(target).keys == successful[0].keys
    assert not (target.parent / (target.name + ".init-lock")).exists()


def test_cookie_and_token_assignments_redacted_without_material():
    result = redact_output(
        "backend cookie=unknown; secret2=value\naccess_token=unknown refresh_token=unknown"
    )
    assert "unknown" not in result and "secret2=value" not in result
