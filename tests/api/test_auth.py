import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from skriller.api import create_app
from skriller.auth import verify_identity
from skriller.settings import Settings


def client(verifier):
    app = create_app(Settings(environment="test", firebase_project_id="test-project"))
    app.state.identity_verifier = verifier
    return TestClient(app)


def claims():
    return {
        "uid": "user-a",
        "aud": "test-project",
        "iss": "https://securetoken.google.com/test-project",
    }


def test_validated_identity_and_missing_token():
    api = client(lambda token, project: claims())
    assert api.get("/v1/me").status_code == 401
    response = api.get("/v1/me", headers={"Authorization": "Bearer synthetic-test-token"})
    assert response.status_code == 200
    assert response.json()["uid"] == "user-a"


def test_wrong_audience_and_expired_verification_fail():
    with pytest.raises(HTTPException) as failure:
        verify_identity("synthetic", "other-project", lambda *_: claims())
    assert failure.value.status_code == 401

    def expired(*_):
        raise ValueError("expired synthetic-secret")

    response = client(expired).get("/v1/me", headers={"Authorization": "Bearer synthetic-secret"})
    assert response.status_code == 401
    assert "synthetic-secret" not in response.text


def test_unconfigured_identity_is_explicitly_unavailable():
    api = TestClient(create_app(Settings(environment="test")))
    response = api.get("/v1/me", headers={"Authorization": "Bearer synthetic"})
    assert response.status_code == 503
