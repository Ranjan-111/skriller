"""Fixed-endpoint Salesforce web-server PKCE and rotating refresh-token transport.

Reuses the product Google OAuth configuration validation and the bounded CRM
transport pattern. This is a confidential server client; no secret enters URLs.
"""

import base64
import hashlib
import json
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from skriller.analytics.google import OAuthConfiguration as ValidatedRedirect
from skriller.connections.keys import KeyUnavailable
from skriller.crm.salesforce import SalesforceUnavailable, validate_instance

SCOPES = "api refresh_token"


@dataclass(frozen=True, repr=False)
class SalesforceConfiguration:
    client_id: str
    client_secret: str
    redirect_uri: str
    production: bool = False
    sandbox: bool = False

    def __post_init__(self):
        try:
            ValidatedRedirect(
                self.client_id, self.client_secret, self.redirect_uri, self.production
            )
        except Exception:  # noqa: BLE001 - opaque shared redirect validation failure
            raise SalesforceUnavailable() from None

    @property
    def origin(self):
        return "https://test.salesforce.com" if self.sandbox else "https://login.salesforce.com"

    @property
    def digest(self):
        return hashlib.sha256(
            json.dumps([self.client_id, self.redirect_uri, SCOPES, self.origin]).encode()
        ).hexdigest()


def authorization_url(config, state, verifier):
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return (
        config.origin
        + "/services/oauth2/authorize?"
        + urlencode(
            {
                "client_id": config.client_id,
                "redirect_uri": config.redirect_uri,
                "response_type": "code",
                "scope": SCOPES,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
    )


def tokens(document, *, previous_refresh=None):
    try:
        instance = validate_instance(document["instance_url"])
        access, refresh = document["access_token"], document.get("refresh_token", previous_refresh)
        if document["token_type"].lower() != "bearer":
            raise ValueError
        if any(
            not isinstance(value, str)
            or not 16 <= len(value) <= 8192
            or any(not 33 <= ord(c) <= 126 for c in value)
            for value in (access, refresh)
        ):
            raise ValueError
        if "scope" in document and set(document["scope"].split()) != set(SCOPES.split()):
            raise ValueError
        return {
            "access_token": access,
            "refresh_token": refresh,
            "instance_url": instance,
            "token_type": "Bearer",
        }
    except Exception:  # noqa: BLE001 - no token/provider documents in exceptions
        raise SalesforceUnavailable() from None


class SalesforceOAuth:
    def __init__(self, transport=None):
        self.transport = transport

    def _post(self, config, values):
        deadline = time.monotonic() + 10
        try:
            with (
                httpx.Client(
                    timeout=httpx.Timeout(5, connect=3),
                    follow_redirects=False,
                    trust_env=False,
                    transport=self.transport,
                ) as client,
                client.stream(
                    "POST",
                    config.origin + "/services/oauth2/token",
                    data={
                        "client_id": config.client_id,
                        "client_secret": config.client_secret,
                        **values,
                    },
                ) as response,
            ):
                if response.status_code != 200:
                    raise SalesforceUnavailable()
                body = bytearray()
                for chunk in response.iter_bytes():
                    if time.monotonic() > deadline or len(body) + len(chunk) > 65536:
                        raise SalesforceUnavailable()
                    body.extend(chunk)

            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError
                    result[key] = value
                return result

            document = json.loads(body, object_pairs_hook=unique)
            if not isinstance(document, dict):
                raise TypeError
            return document
        except Exception:  # noqa: BLE001 - redact HTTP/provider/form details
            raise SalesforceUnavailable() from None

    def exchange(self, config, code, verifier):
        return tokens(
            self._post(
                config,
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "code_verifier": verifier,
                    "redirect_uri": config.redirect_uri,
                },
            )
        )

    def refresh(self, config, refresh_token):
        return tokens(
            self._post(config, {"grant_type": "refresh_token", "refresh_token": refresh_token}),
            previous_refresh=refresh_token,
        )


def configuration(settings):
    if not (
        settings.salesforce_oauth_client_id
        and settings.salesforce_oauth_client_secret
        and settings.salesforce_oauth_redirect_uri
    ):
        raise KeyUnavailable()
    return SalesforceConfiguration(
        settings.salesforce_oauth_client_id,
        settings.salesforce_oauth_client_secret.get_secret_value(),
        settings.salesforce_oauth_redirect_uri,
        production=settings.environment == "production",
        sandbox=settings.salesforce_oauth_sandbox,
    )
