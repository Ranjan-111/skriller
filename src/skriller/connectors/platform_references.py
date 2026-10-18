"""Indexed platform routing using copied Agent-Reach channels; no source reads."""

import re
from typing import Literal
from urllib.parse import urlsplit

from agent_reach.channels.linkedin import LinkedInChannel
from agent_reach.channels.reddit import RedditChannel
from pydantic import model_validator

from skriller.connectors.candidates import native_reference
from skriller.contracts import Contract

ResourceKind = Literal["profile", "company", "page", "post", "comment", "community", "unknown"]


class PlatformReference(Contract):
    source: Literal["linkedin", "reddit", "instagram", "facebook"]
    resource_kind: ResourceKind
    discovery_backend: Literal[
        "exa_keyless", "linkedin_mcp", "opencli_instagram", "opencli_facebook"
    ] = "exa_keyless"
    access: Literal["indexed_reference_only", "connected_search_reference_only"] = (
        "indexed_reference_only"
    )
    direct_read_status: Literal["not_attempted"] = "not_attempted"
    subject_identity: Literal["unknown"] = "unknown"

    @model_validator(mode="after")
    def origin_matches_access(self):
        connected = {
            "linkedin_mcp": "linkedin",
            "opencli_instagram": "instagram",
            "opencli_facebook": "facebook",
        }
        if (self.discovery_backend in connected) != (
            self.access == "connected_search_reference_only"
        ):
            raise ValueError("Search origin and access description must agree")
        if self.discovery_backend in connected and self.source != connected[self.discovery_backend]:
            raise ValueError("Connected reference must match its source backend")
        return self


def connected_linkedin_reference(url: str) -> dict | None:
    reference = indexed_platform_reference(url)
    if reference is None or reference["source"] != "linkedin":
        return None
    return PlatformReference.model_validate(
        {
            **reference,
            "discovery_backend": "linkedin_mcp",
            "access": "connected_search_reference_only",
        }
    ).model_dump()


def connected_social_reference(url: str, source: Literal["instagram", "facebook"]) -> dict:
    if source == "instagram":
        from skriller.connectors.instagram_read import InstagramRead

        parts = urlsplit(url)
        request = InstagramRead(username=parts.path.strip("/"))
        if url != request.target_url():
            raise ValueError("A canonical Instagram profile is required")
        return PlatformReference(
            source="instagram",
            resource_kind="profile",
            discovery_backend="opencli_instagram",
            access="connected_search_reference_only",
        ).model_dump()
    from skriller.connectors.facebook_read import reference_kind

    kind = reference_kind(url)
    if kind is None:
        raise ValueError("Facebook resource scope is unsupported")
    return PlatformReference(
        source="facebook",
        resource_kind="page"
        if kind == "page_reference"
        else "post"
        if kind == "content_reference"
        else "unknown",
        discovery_backend="opencli_facebook",
        access="connected_search_reference_only",
    ).model_dump()


def indexed_platform_reference(url: str) -> dict | None:
    """Classify a URL reference without reading profiles or inferring subjects.

    Channel host routing is copied upstream behavior. Resource classification is
    bounded product glue, reusing the existing native permalink discriminator.
    Unrecognized platform paths remain explicit unknowns.
    """
    try:
        linkedin = LinkedInChannel().can_handle(url)
        reddit = RedditChannel().can_handle(url)
        if not linkedin and not reddit:
            return None
        path = urlsplit(url).path
        native = native_reference(url)
    except ValueError:
        return None
    kind: ResourceKind = "unknown"
    if native:
        kind = "comment" if native["namespace"] == "reddit_comment" else "post"
    elif linkedin:
        if re.fullmatch(r"/in/[^/]+/?", path):
            kind = "profile"
        elif re.fullmatch(r"/company/[^/]+/?", path):
            kind = "company"
    elif re.fullmatch(r"/r/[A-Za-z0-9_]{1,32}/?", path):
        kind = "community"
    elif re.fullmatch(r"/(?:user|u)/[A-Za-z0-9_-]{1,32}/?", path):
        kind = "profile"
    return PlatformReference(
        source="linkedin" if linkedin else "reddit", resource_kind=kind
    ).model_dump()
