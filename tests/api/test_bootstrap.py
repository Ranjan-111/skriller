import pytest
from fastapi.testclient import TestClient

from skriller.api import broker_available, create_app, database_available
from skriller.settings import Settings


def test_liveness_and_dependency_failure(monkeypatch):
    monkeypatch.setattr("skriller.api.database_available", lambda _: False)
    monkeypatch.setattr("skriller.api.broker_available", lambda _: True)
    monkeypatch.setattr("skriller.api.worker_available", lambda _: True)
    client = TestClient(create_app(Settings(environment="test")))
    assert client.get("/health/live").status_code == 200
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["dependencies"] == {"database": False, "broker": True, "worker": True}
    assert "local-development" not in response.text


def test_missing_worker_does_not_report_research_ready(monkeypatch):
    monkeypatch.setattr("skriller.api.database_available", lambda _: True)
    monkeypatch.setattr("skriller.api.broker_available", lambda _: True)
    monkeypatch.setattr("skriller.api.worker_available", lambda _: False)
    response = TestClient(create_app(Settings(environment="test"))).get("/health/ready")
    assert response.status_code == 503
    assert response.json()["dependencies"]["worker"] is False


def test_production_cannot_enable_demo_credentials():
    with pytest.raises(ValueError, match="Demo authentication"):
        Settings(environment="production", allow_demo_auth=True)


@pytest.mark.parametrize(
    "options",
    [
        {"enable_page_extraction": True},
        {"public_collection_proxy_url": "http://untrusted.example:8080"},
        {"enable_dynamic_collection": True},
        {"environment": "production", "public_collection_proxy_url": "http://127.0.0.1:8080"},
    ],
)
def test_unconfigured_or_unisolated_collection_rejected_before_runtime(options):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **options)


def test_production_keyless_search_requires_commercial_terms_review():
    production = {
        "environment": "production",
        "firebase_project_id": "skriller-production",
        "database_url": "postgresql+psycopg://app:secret@db.example/skriller",
        "application_database_url": "postgresql+psycopg://app:secret@db.example/skriller",
        "broker_url": "amqp://app:secret@mq.example/skriller",
    }
    with pytest.raises(ValueError, match="commercial-use terms"):
        Settings(**production)
    reviewed = Settings(**production, search_commercial_terms_confirmed=True)
    assert reviewed.search_provider == "exa_keyless"
    disabled = Settings(**production, search_provider="disabled")
    assert disabled.search_provider == "disabled"


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
