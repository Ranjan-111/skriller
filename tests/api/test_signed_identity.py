import json
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from google.auth import crypt, jwt

from skriller.auth import verify_identity


@pytest.fixture
def signed_identity(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    signer = crypt.RSASigner.from_string(private, key_id="fixture-key")

    class Certificates:
        status = 200
        data = json.dumps({"fixture-key": public.decode()}).encode()

    monkeypatch.setattr(
        "skriller.auth._certificate_request", lambda *_args, **_kwargs: Certificates()
    )
    now = int(time.time())
    claims = {
        "sub": "signed-user",
        "aud": "test-project",
        "iss": "https://securetoken.google.com/test-project",
        "iat": now,
        "exp": now + 600,
    }
    return signer, claims


def test_real_google_verifier_checks_rsa_signature(signed_identity):
    signer, claims = signed_identity
    token = jwt.encode(signer, claims).decode()
    assert verify_identity(token, "test-project").uid == "signed-user"
    forged = token[:-8] + "forged00"
    with pytest.raises(HTTPException) as failure:
        verify_identity(forged, "test-project")
    assert failure.value.status_code == 401
    assert forged not in failure.value.detail


@pytest.mark.parametrize(
    "changes",
    [
        {"exp": 1},
        {"aud": "wrong-project"},
        {"iss": "https://attacker.example"},
        {"iat": 9999999999},
        {"sub": ""},
    ],
)
def test_signed_but_invalid_claims_are_denied(signed_identity, changes):
    signer, claims = signed_identity
    with pytest.raises(HTTPException) as failure:
        verify_identity(jwt.encode(signer, {**claims, **changes}).decode(), "test-project")
    assert failure.value.status_code == 401


def test_custom_uid_claim_cannot_override_verified_subject(signed_identity):
    signer, claims = signed_identity
    token = jwt.encode(signer, {**claims, "uid": "other-user"}).decode()
    assert verify_identity(token, "test-project").uid == "signed-user"
