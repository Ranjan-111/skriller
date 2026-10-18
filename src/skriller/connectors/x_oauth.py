"""X confidential-client PKCE transport adapted from crm.oauth.

Only read scopes and fixed authentication endpoints are supported. There are no
timeline writes, browser cookies, automatic retries or raw provider errors.
"""

import base64
import hashlib
import json
import re
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from skriller.analytics.google import OAuthConfiguration as ValidatedRedirect

SCOPES = "tweet.read users.read offline.access"


class XOAuthUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("X authorization needs configuration or reconnection")


@dataclass(frozen=True, repr=False)
class XOAuthConfiguration:
    client_id: str
    client_secret: str
    redirect_uri: str
    production: bool = False

    def __post_init__(self):
        try:
            ValidatedRedirect(
                self.client_id, self.client_secret, self.redirect_uri, self.production
            )
            if any(
                any(not 33 <= ord(c) <= 126 for c in item)
                for item in (self.client_id, self.client_secret)
            ):
                raise ValueError
        except Exception:  # noqa: BLE001 - configuration must not appear in errors
            raise XOAuthUnavailable() from None

    @property
    def digest(self):
        return hashlib.sha256(
            json.dumps([self.client_id, self.redirect_uri, SCOPES, "api.x.com"]).encode()
        ).hexdigest()


def authorization_url(config, state, verifier):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", state) or not re.fullmatch(
        r"[A-Za-z0-9_-]{43,128}", verifier
    ):
        raise XOAuthUnavailable()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    return "https://x.com/i/oauth2/authorize?" + urlencode(
        {
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
            "code_challenge": challenge.decode(),
            "code_challenge_method": "S256",
        }
    )


def tokens(document):
    """Require a new refresh token on every exchange; never reuse uncertain rotation."""
    try:
        if not isinstance(document, dict) or document.get("token_type", "").lower() != "bearer":
            raise ValueError
        if set(document["scope"].split()) != set(SCOPES.split()):
            raise ValueError
        expiry = document["expires_in"]
        if type(expiry) is not int or not 60 <= expiry <= 86400:
            raise ValueError
        for key in ("access_token", "refresh_token"):
            value = document[key]
            if (
                not isinstance(value, str)
                or not 16 <= len(value) <= 8192
                or any(not 33 <= ord(c) <= 126 for c in value)
            ):
                raise ValueError
        return {key: document[key] for key in ("access_token", "refresh_token", "expires_in")}
    except Exception:  # noqa: BLE001 - reject extra/write scopes without disclosing tokens
        raise XOAuthUnavailable() from None


class XOAuth:
    endpoint = "https://api.x.com/2/oauth2/token"
    unavailable: type[RuntimeError] = XOAuthUnavailable

    def receipt(self, document, values):
        tokens(document)
        return document

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
                    self.endpoint,
                    auth=httpx.BasicAuth(config.client_id, config.client_secret),
                    data=values,
                    headers={"User-Agent": config.user_agent}
                    if hasattr(config, "user_agent")
                    else {},
                ) as response,
            ):
                if response.status_code != 200:
                    raise self.unavailable()
                body = bytearray()
                for chunk in response.iter_bytes():
                    if time.monotonic() > deadline or len(body) + len(chunk) > 65536:
                        raise self.unavailable()
                    body.extend(chunk)

            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError
                    result[key] = value
                return result

            document = json.loads(body, object_pairs_hook=unique)
            return self.receipt(document, values)
        except Exception:  # noqa: BLE001 - sanitize HTTP/form/provider secrets
            raise self.unavailable() from None

    def exchange(self, config, code, verifier):
        if (
            not isinstance(code, str)
            or not 1 <= len(code) <= 8192
            or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", verifier)
        ):
            raise self.unavailable()
        return self._post(
            config,
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": config.redirect_uri,
            },
        )

    def refresh(self, config, refresh_token):
        return self._post(config, {"grant_type": "refresh_token", "refresh_token": refresh_token})


def configuration(settings):
    if not (
        settings.x_oauth_client_id
        and settings.x_oauth_client_secret
        and settings.x_oauth_redirect_uri
    ):
        raise XOAuthUnavailable()
    return XOAuthConfiguration(
        settings.x_oauth_client_id,
        settings.x_oauth_client_secret.get_secret_value(),
        settings.x_oauth_redirect_uri,
        production=settings.environment == "production",
    )
