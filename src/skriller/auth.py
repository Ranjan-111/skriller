"""Verify app identity; workspace and source permissions are separate checks."""

from collections.abc import Callable
from dataclasses import dataclass

import firebase_admin
from fastapi import HTTPException, Request
from firebase_admin import auth as firebase_auth


@dataclass(frozen=True)
class Identity:
    uid: str
    email: str | None = None


def firebase_verify(token: str, project: str) -> dict:
    name = f"skriller-{project}"
    try:
        app = firebase_admin.get_app(name)
    except ValueError:
        app = firebase_admin.initialize_app(options={"projectId": project}, name=name)
    # The SDK verifies signatures, expiry, issuer and project audience.
    return firebase_auth.verify_id_token(token, app=app)


def verify_identity(token: str, project: str, verifier: Callable = firebase_verify) -> Identity:
    try:
        claims = verifier(token, project)
        uid = claims.get("uid") or claims.get("sub")
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
