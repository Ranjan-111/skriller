"""Public-only contract around the attributed OpenCLI read subset.

This is output validation, not scraping or an enabled execution route. The caller
must separately enforce tenant credentials, isolated networking and call budgets.
"""

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from skriller.connectors.social_read import SocialData, bounded_rows

HANDLE = re.compile(r"[A-Za-z0-9_](?:[A-Za-z0-9._]{0,28}[A-Za-z0-9_])?")
RESERVED = {"accounts", "api", "direct", "explore", "reels", "stories", "challenge"}
Count = Annotated[int, Field(strict=True, ge=0, le=1_000_000_000_000)]


def public_handle(value: str) -> str:
    if not isinstance(value, str) or not HANDLE.fullmatch(value) or value.casefold() in RESERVED:
        raise ValueError("An explicit Instagram profile handle is required")
    return value


class InstagramSearch(SocialData):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=10, ge=1, le=10)

    @model_validator(mode="after")
    def bounded_query(self):
        if not self.query.strip() or any(ord(char) < 32 for char in self.query):
            raise ValueError("A nonempty single-line search query is required")
        return self


class InstagramRead(SocialData):
    username: str

    @model_validator(mode="after")
    def explicit_profile(self):
        public_handle(self.username)
        return self

    def target_url(self) -> str:
        return "https://www.instagram.com/" + self.username + "/"


class InstagramReference(SocialData):
    username: str
    name: str = Field(max_length=500)
    source_url: str
    observed_at: datetime
    source: Literal["instagram"] = "instagram"
    visibility: Literal["public"] = "public"
    resource_kind: Literal["profile"] = "profile"
    subject_identity: Literal["unknown"] = "unknown"
    account_kind: Literal["unknown"] = "unknown"
    verified: bool | None = None

    @model_validator(mode="after")
    def aligned_reference(self):
        if (
            self.source_url != InstagramRead(username=self.username).target_url()
            or self.observed_at.tzinfo is None
            or self.observed_at.utcoffset() is None
        ):
            raise ValueError("An aligned profile URL and aware observation time are required")
        return self


class InstagramProfile(InstagramReference):
    bio_excerpt: str = Field(max_length=120)
    followers: Count | None
    following: Count | None
    posts: Count | None
    coverage_complete: Literal[False] = False
    owner_analytics: Literal["unavailable"] = "unavailable"


def parse_profile_response(payload, request: InstagramRead, *, observed_at: datetime):
    rows = bounded_rows(payload)
    if len(rows) != 1:
        raise ValueError("Exactly one requested profile is required")
    row = rows[0]
    if (
        row.get("private") is not False
        or not isinstance(row.get("username"), str)
        or row["username"].casefold() != request.username.casefold()
        or set(row)
        - {
            "private",
            "username",
            "name",
            "bio",
            "followers",
            "following",
            "posts",
            "verified",
            "avatar_url",
        }
    ):
        raise ValueError("Profile visibility or requested identity is unconfirmed")
    return InstagramProfile(
        username=request.username,
        name=row.get("name", ""),
        source_url=request.target_url(),
        observed_at=observed_at,
        verified=row.get("verified"),
        bio_excerpt=row.get("bio", ""),
        followers=row.get("followers"),
        following=row.get("following"),
        posts=row.get("posts"),
    )


def parse_search_response(payload, request: InstagramSearch, *, observed_at: datetime):
    rows = bounded_rows(payload)
    if len(rows) > request.limit:
        raise ValueError("Search output exceeds the requested bound")
    references = []
    seen = set()
    for row in rows:
        if row.get("private") is not False or set(row) - {
            "rank",
            "username",
            "name",
            "verified",
            "private",
            "url",
            "avatar_url",
        }:
            raise ValueError("Only adapted explicitly public search references are accepted")
        username = public_handle(row.get("username"))
        if row.get("url") != "https://www.instagram.com/" + username:
            raise ValueError("Search reference URL does not match its handle")
        reference = InstagramReference(
            username=username,
            name=row.get("name", ""),
            source_url=InstagramRead(username=username).target_url(),
            observed_at=observed_at,
            verified=row.get("verified"),
        )
        if username.casefold() not in seen:
            references.append(reference)
            seen.add(username.casefold())
    return references
