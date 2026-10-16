"""Bounded fixed-endpoint Google OAuth and owner-channel discovery."""

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlencode, urlsplit

import httpx

SCOPES = (
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
)


class AnalyticsUnavailable(RuntimeError):
    """Opaque failure codes only; never retain provider bodies or credentials."""

    def __init__(self, code="analytics_connection_unavailable"):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class OAuthConfiguration:
    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str
    production: bool = False

    def __post_init__(self):
        url = urlsplit(self.redirect_uri)
        local = url.hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            not self.client_id
            or len(self.client_id) > 512
            or not self.client_secret
            or len(self.client_secret) > 4096
            or len(self.redirect_uri) > 2048
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or (
                url.scheme != "https"
                and not (url.scheme == "http" and local and not self.production)
            )
        ):
            raise AnalyticsUnavailable("analytics_oauth_not_configured")

    @property
    def digest(self):
        return hashlib.sha256(
            json.dumps([self.client_id, self.redirect_uri, SCOPES]).encode()
        ).hexdigest()


def authorization_url(config: OAuthConfiguration, state: str, verifier: str):
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
        {
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "false",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )


def _json(client, method, url, **kwargs):
    try:
        with client.stream(method, url, **kwargs) as response:
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > 65536:
                    raise AnalyticsUnavailable("analytics_response_limit")
        result = json.loads(body)
        if not isinstance(result, dict):
            raise TypeError
        if response.status_code != 200:
            error = result.get("error")
            entries = error.get("errors", []) if isinstance(error, dict) else []
            reasons = (
                {entry.get("reason") for entry in entries if isinstance(entry, dict)}
                if isinstance(entries, list)
                else set()
            )
            if response.status_code == 429 or reasons & {
                "quotaExceeded",
                "dailyLimitExceeded",
                "rateLimitExceeded",
                "userRateLimitExceeded",
            }:
                raise AnalyticsUnavailable("analytics_quota_exhausted")
            if response.status_code == 401:
                raise AnalyticsUnavailable("analytics_authorization_expired")
            if response.status_code >= 500:
                raise AnalyticsUnavailable("analytics_provider_unavailable")
            raise AnalyticsUnavailable("analytics_provider_denied")
        return result
    except AnalyticsUnavailable:
        raise
    except Exception:  # noqa: BLE001 - no provider details cross the boundary
        raise AnalyticsUnavailable("analytics_provider_unavailable") from None


def validate_tokens(tokens):
    if (
        not isinstance(tokens, dict)
        or tokens.get("token_type") != "Bearer"
        or type(tokens.get("expires_in")) is not int
        or not 1 <= tokens["expires_in"] <= 86400
        or not isinstance(tokens.get("scope"), str)
        or set(tokens["scope"].split()) != set(SCOPES)
        or not isinstance(tokens.get("access_token"), str)
        or not 1 <= len(tokens["access_token"]) <= 8192
        or any(not 33 <= ord(char) <= 126 for char in tokens["access_token"])
        or (
            "refresh_token" in tokens
            and (
                not isinstance(tokens["refresh_token"], str)
                or not 1 <= len(tokens["refresh_token"]) <= 8192
            )
        )
    ):
        raise AnalyticsUnavailable("analytics_scope_or_token_invalid")
    return {key: tokens[key] for key in ("access_token", "refresh_token") if key in tokens}


class GoogleAnalyticsOAuth:
    def report(self, access_token, channel_id, start_date, end_date, metrics):
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            return _json(
                client,
                "GET",
                "https://youtubeanalytics.googleapis.com/v2/reports",
                params={
                    "ids": "channel==" + channel_id,
                    "startDate": start_date.isoformat(),
                    "endDate": end_date.isoformat(),
                    "dimensions": "day",
                    "metrics": ",".join(metrics),
                    "sort": "day",
                    "maxResults": 31,
                },
                headers={"Authorization": "Bearer " + access_token},
            )

    def refresh(self, config: OAuthConfiguration, refresh_token: str):
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            tokens = _json(
                client,
                "POST",
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": config.client_id,
                    "client_secret": config.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        # RFC 6749 permits scope omission when the original scope is unchanged.
        tokens.setdefault("scope", " ".join(SCOPES))
        validate_tokens(tokens)
        tokens.setdefault("refresh_token", refresh_token)
        return tokens

    def exchange(self, config: OAuthConfiguration, code: str, verifier: str):
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            tokens = _json(
                client,
                "POST",
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": config.client_id,
                    "client_secret": config.client_secret,
                    "redirect_uri": config.redirect_uri,
                    "code": code,
                    "code_verifier": verifier,
                    "grant_type": "authorization_code",
                },
            )
            validated = validate_tokens(tokens)
            channels = _json(
                client,
                "GET",
                "https://www.googleapis.com/youtube/v3/channels",
                params={"part": "id", "mine": "true", "maxResults": 2},
                headers={"Authorization": "Bearer " + validated["access_token"]},
            )
        items = channels.get("items")
        if (
            not isinstance(items, list)
            or len(items) != 1
            or not isinstance(items[0], dict)
            or not isinstance(items[0].get("id"), str)
            or not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", items[0]["id"])
            or channels.get("nextPageToken")
        ):
            raise AnalyticsUnavailable("analytics_owner_channel_unavailable")
        return tokens, items[0]["id"]
