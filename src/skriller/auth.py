"""Verify app identity; workspace and source permissions are separate checks."""

from collections.abc import Callable
from dataclasses import dataclass

import requests
from cachecontrol import CacheControl
from fastapi import HTTPException, Request
from google.auth.transport.requests import Request as CertificateRequest
from google.oauth2.id_token import verify_firebase_token


@dataclass(frozen=True)
class Identity:
    uid: str
    email: str | None = None


_certificate_transport = CertificateRequest(session=CacheControl(requests.Session()))


def _certificate_request(url, method="GET", **kwargs):
    return _certificate_transport(url, method=method, timeout=5, **kwargs)


def firebase_verify(token: str, project: str) -> dict:
    # Public-key verification requires no privileged Firebase service-account key.
    # Google Auth checks signature, iat/expiry and audience; issuer is checked below.
    return verify_firebase_token(token, _certificate_request, audience=project)


def verify_identity(token: str, project: str, verifier: Callable = firebase_verify) -> Identity:
    try:
        claims = verifier(token, project)
        uid = claims.get("sub")
        if not isinstance(uid, str) or not uid or len(uid) > 128:
            raise ValueError("Invalid subject")
        if (
            claims.get("aud") != project
            or claims.get("iss") != f"https://securetoken.google.com/{project}"
        ):
            raise ValueError("Invalid identity audience")
        return Identity(uid=uid, email=claims.get("email"))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Sign-in token is invalid or expired") from exc


def require_identity(request: Request) -> Identity:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer ") or not header[7:].strip():
        raise HTTPException(status_code=401, detail="Sign in to use this workspace")
    settings = request.app.state.settings
    if not settings.firebase_project_id:
        raise HTTPException(status_code=503, detail="App sign-in has not been configured")
    verifier = getattr(request.app.state, "identity_verifier", firebase_verify)
    return verify_identity(header[7:], settings.firebase_project_id, verifier)
