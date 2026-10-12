import pytest
from fastapi.testclient import TestClient

from skriller.api import broker_available, create_app, database_available
from skriller.settings import Settings


def test_liveness_and_dependency_failure(monkeypatch):
    monkeypatch.setattr("skriller.api.database_available", lambda _: False)
    monkeypatch.setattr("skriller.api.broker_available", lambda _: True)
    client = TestClient(create_app(Settings(environment="test")))
    assert client.get("/health/live").status_code == 200
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["dependencies"] == {"database": False, "broker": True}
    assert "local-development" not in response.text


def test_production_cannot_enable_demo_credentials():
    with pytest.raises(ValueError, match="Demo authentication"):
        Settings(environment="production", allow_demo_auth=True)


@pytest.mark.integration_db
def test_real_database_and_broker_readiness():
    settings = Settings(environment="test")
    assert database_available(settings.database_url)
    assert broker_available(settings.broker_url)
    response = TestClient(create_app(settings)).get("/health/ready")
    assert response.status_code == 200


def test_local_object_volume_is_private_and_lifecycle_wired(tmp_path):
    import stat

    directory = tmp_path / "private-evidence"
    application = create_app(Settings(environment="test", object_directory=str(directory)))
    with TestClient(application) as client:
        assert client.get("/health/live").status_code == 200
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        assert application.state.evidence_storage.backend.directory == directory
