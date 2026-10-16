import json

import pytest

from skriller.billing_runtime import read_configuration


def configuration():
    return {
        "operator_database_url": "postgresql+psycopg://fixture:private@127.0.0.1/fixture",
        "endpoints": [
            {
                "provider": "stripe",
                "webhook_secret": "synthetic_secret_only",
                "api_key": "sk_test_fixture_only",
                "stripe_version": "2025-06-30.basil",
            }
        ],
    }


def test_private_file_loads_and_secrets_stay_redacted(tmp_path):
    path = tmp_path / "billing.json"
    path.write_text(json.dumps(configuration()))
    path.chmod(0o600)
    config, endpoints = read_configuration(path)
    assert endpoints[0].scope == "self:test"
    assert "sk_test_fixture" not in repr(endpoints) and "private@" not in repr(config)


@pytest.mark.parametrize(
    "kind", ["permissions", "symlink", "too_large", "invalid", "duplicate", "sqlite", "extra"]
)
def test_invalid_file_fails_without_disclosing_content(tmp_path, kind):
    path = tmp_path / "config.json"
    doc = configuration()
    if kind == "duplicate":
        doc["endpoints"] *= 2
    if kind == "sqlite":
        doc["operator_database_url"] = "sqlite:///fixture.db"
    if kind == "extra":
        doc["dangerous"] = "private_sentinel"
    path.write_text(json.dumps(doc) if kind != "invalid" else "private_sentinel")
    path.chmod(0o600)
    if kind == "permissions":
        path.chmod(0o644)
    if kind == "too_large":
        path.write_text("private_sentinel" * 32768)
    if kind == "symlink":
        link = tmp_path / "link.json"
        link.symlink_to(path)
        path = link
    with pytest.raises(ValueError) as error:
        read_configuration(path)
    assert "sentinel" not in str(error.value) and "sk_test" not in str(error.value)
