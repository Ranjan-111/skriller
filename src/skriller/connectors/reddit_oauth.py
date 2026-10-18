"""Read-only Reddit confidential OAuth, reusing the reviewed X transport bounds.

Protocol reference: github.com/reddit-archive/reddit/wiki/OAuth2. This adapter
requests only read, uses duration=permanent, and accepts nonrotating refresh.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from urllib.parse import urlencode

from skriller.connectors.x_oauth import XOAuth, XOAuthConfiguration

SCOPES = "read"


class RedditOAuthUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("Reddit authorization needs configuration or reconnection")


@dataclass(frozen=True, repr=False)
class RedditOAuthConfiguration:
    client_id: str
    client_secret: str
    redirect_uri: str
    user_agent: str
    production: bool = False

    def __post_init__(self):
        try:
            XOAuthConfiguration(
                self.client_id, self.client_secret, self.redirect_uri, self.production
            )
            if not 16 <= len(self.user_agent) <= 256 or any(
                not 32 <= ord(c) <= 126 for c in self.user_agent
            ):
                raise ValueError
        except Exception:  # noqa: BLE001 - keep operator configuration private
            raise RedditOAuthUnavailable() from None

    @property
    def digest(self):
        return hashlib.sha256(
            json.dumps(
                [self.client_id, self.redirect_uri, SCOPES, "www.reddit.com", self.user_agent]
            ).encode()
        ).hexdigest()


def authorization_url(config, state, _verifier=None):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", state):
        raise RedditOAuthUnavailable()
    return "https://www.reddit.com/api/v1/authorize?" + urlencode(
        {
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
            "duration": "permanent",
        }
    )


def tokens(document):
    # Reuse strict token/expiry validation while enforcing Reddit's read scope.
    from skriller.connectors.x_oauth import SCOPES as X_SCOPES
    from skriller.connectors.x_oauth import tokens as x_tokens

    try:
        if not isinstance(document, dict) or document.get("scope") != SCOPES:
            raise ValueError
        return x_tokens({**document, "scope": X_SCOPES})
    except Exception:  # noqa: BLE001 - never expose provider receipts
        raise RedditOAuthUnavailable() from None


class RedditOAuth(XOAuth):
    endpoint = "https://www.reddit.com/api/v1/access_token"
    unavailable = RedditOAuthUnavailable

    def receipt(self, document, values):
        if not isinstance(document, dict):
            raise RedditOAuthUnavailable()
        # Reddit refresh receipts may omit the original permanent refresh grant.
        # The consumed in-memory grant may be retained only after a valid receipt.
        if values.get("grant_type") == "refresh_token" and "refresh_token" not in document:
            document = {**document, "refresh_token": values["refresh_token"]}
        tokens(document)
        return document

    def exchange(self, config, code, _verifier=None):
        if (
            not isinstance(code, str)
            or not 1 <= len(code) <= 8192
            or any(not 33 <= ord(c) <= 126 for c in code)
        ):
            raise RedditOAuthUnavailable()
        return self._post(
            config,
            {"grant_type": "authorization_code", "code": code, "redirect_uri": config.redirect_uri},
        )


def configuration(settings):
    if not (
        settings.reddit_oauth_client_id
        and settings.reddit_oauth_client_secret
        and settings.reddit_oauth_redirect_uri
        and settings.reddit_oauth_user_agent
    ):
        raise RedditOAuthUnavailable()
    return RedditOAuthConfiguration(
        settings.reddit_oauth_client_id,
        settings.reddit_oauth_client_secret.get_secret_value(),
        settings.reddit_oauth_redirect_uri,
        settings.reddit_oauth_user_agent,
        production=settings.environment == "production",
    )
