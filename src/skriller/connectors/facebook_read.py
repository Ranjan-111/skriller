"""Preserve copied Facebook read output without inventing public/company scope."""

import re
from datetime import datetime
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import Field, model_validator

from skriller.connectors.social_read import SocialData, bounded_rows

RESERVED = {
    "logout",
    "logout.php",
    "login.php",
    "signup",
    "register",
    "reg",
    "recover",
    "ajax",
    "api",
    "graphql",
    "dialog",
    "plugins",
    "connect",
    "home.php",
    "groups",
    "login",
    "checkpoint",
    "settings",
    "me",
    "profile.php",
    "search",
    "friends",
    "privacy",
    "policies",
    "help",
    "messages",
    "notifications",
    "marketplace",
    "gaming",
}


class FacebookSearch(SocialData):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=10, ge=1, le=10)

    @model_validator(mode="after")
    def bounded_query(self):
        if not self.query.strip() or any(ord(char) < 32 for char in self.query):
            raise ValueError("A nonempty single-line query is required")
        return self


class FacebookRead(SocialData):
    username: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]{0,99}$")

    @model_validator(mode="after")
    def explicit_profile(self):
        if self.username.casefold() in RESERVED:
            raise ValueError("An explicit named profile or page is required")
        return self

    def target_url(self):
        return "https://www.facebook.com/" + self.username


def source_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("A bounded source URL is required")
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or parts.hostname != "www.facebook.com"
        or parts.port not in {None, 443}
        or parts.username
        or parts.password
        or parts.fragment
    ):
        raise ValueError("A canonical Facebook source is required")
    return parts


def reference_kind(value) -> Literal["page_reference", "content_reference", "unknown"] | None:
    kind: Literal["page_reference", "content_reference", "unknown"]
    parts = source_url(value)
    route = parts.path.casefold()
    # Page visibility does not grant group, private, owner or person scope.
    if route.startswith(("/groups/", "/events/", "/watch", "/reel/", "/photo.php")):
        return None
    if re.fullmatch(r"/pages/[A-Za-z0-9.-]+/[0-9]+/?", route):
        kind = "page_reference"
        allowed_query = set()
    elif re.fullmatch(r"/[A-Za-z0-9.-]+/posts/[A-Za-z0-9]+/?", route) or route in {
        "/permalink.php",
        "/story.php",
    }:
        kind = "content_reference"
        allowed_query = {"story_fbid", "story_id", "fbid", "id"}
    elif re.fullmatch(r"/[A-Za-z0-9.-]+/?", route) and route.strip("/") not in RESERVED:
        kind = "unknown"
        allowed_query = set()
    else:
        return None
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if route in {"/permalink.php", "/story.php"} and not any(
        key in {"story_fbid", "story_id", "fbid"} for key, _ in pairs
    ):
        raise ValueError("A specific content identity is required")
    if any(
        key not in allowed_query or not re.fullmatch(r"[0-9]{1,40}", value) for key, value in pairs
    ) or len({key for key, _ in pairs}) != len(pairs):
        raise ValueError("Unexpected source identity parameters")
    return kind


class FacebookReference(SocialData):
    title: str = Field(min_length=1, max_length=80)
    excerpt: str = Field(max_length=150)
    source_url: str
    observed_at: datetime
    source: Literal["facebook"] = "facebook"
    resource_kind: Literal["page_reference", "content_reference", "unknown"]
    visibility: Literal["unknown"] = "unknown"
    company_identity: Literal["unknown"] = "unknown"
    subject_identity: Literal["unknown"] = "unknown"
    group_access: Literal["unavailable"] = "unavailable"

    @model_validator(mode="after")
    def bounded_observation(self):
        if reference_kind(self.source_url) != self.resource_kind:
            raise ValueError("Resource scope does not match its source URL")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("An aware observation time is required")
        return self


class FacebookProfile(SocialData):
    name: str = Field(min_length=1, max_length=500)
    username: str
    source_url: str
    observed_at: datetime
    friends_display: str | None = Field(max_length=100)
    followers_display: str | None = Field(max_length=100)
    source: Literal["facebook"] = "facebook"
    visibility: Literal["unknown"] = "unknown"
    company_identity: Literal["unknown"] = "unknown"
    subject_identity: Literal["unknown"] = "unknown"
    group_access: Literal["unavailable"] = "unavailable"
    coverage_complete: Literal[False] = False

    @model_validator(mode="after")
    def aligned_profile(self):
        if (
            self.source_url != FacebookRead(username=self.username).target_url()
            or self.observed_at.tzinfo is None
            or self.observed_at.utcoffset() is None
        ):
            raise ValueError("An aligned source and aware observation time are required")
        return self


class FacebookSearchPage(SocialData):
    references: list[FacebookReference] = Field(max_length=10)
    omitted_unsupported: int = Field(ge=0, le=10)


def parse_profile_response(payload, request: FacebookRead, *, observed_at: datetime):
    rows = bounded_rows(payload)
    if len(rows) != 1:
        raise ValueError("Exactly one requested profile is required")
    row = rows[0]
    if set(row) != {"name", "username", "friends", "followers", "url"}:
        raise ValueError("Unexpected profile output")
    if row["username"] != request.username or row["url"] not in {
        request.target_url(),
        request.target_url() + "/",
    }:
        raise ValueError("Profile output does not match its requested resource")
    return FacebookProfile(
        name=row["name"],
        username=request.username,
        source_url=request.target_url(),
        observed_at=observed_at,
        friends_display=None if row["friends"] == "-" else row["friends"],
        followers_display=None if row["followers"] == "-" else row["followers"],
    )


def parse_search_response(payload, request: FacebookSearch, *, observed_at: datetime):
    rows = bounded_rows(payload)
    if len(rows) > request.limit:
        raise ValueError("Search output exceeds its requested bound")
    references, seen, omitted = [], set(), 0
    for row in rows:
        if set(row) != {"index", "title", "text", "url"}:
            raise ValueError("Unexpected search output")
        kind = reference_kind(row["url"])
        if kind is None:
            omitted += 1
            continue
        reference = FacebookReference(
            title=row["title"],
            excerpt=row["text"],
            source_url=row["url"],
            observed_at=observed_at,
            resource_kind=kind,
        )
        if reference.source_url not in seen:
            references.append(reference)
            seen.add(reference.source_url)
    return FacebookSearchPage(references=references, omitted_unsupported=omitted)
