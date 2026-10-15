"""Indexed platform routing using copied Agent-Reach channels; no source reads."""

import re
from typing import Literal
from urllib.parse import urlsplit

from agent_reach.channels.linkedin import LinkedInChannel
from agent_reach.channels.reddit import RedditChannel

from skriller.connectors.candidates import native_reference
from skriller.contracts import Contract

ResourceKind = Literal["profile", "company", "post", "comment", "community", "unknown"]


class PlatformReference(Contract):
    source: Literal["linkedin", "reddit"]
    resource_kind: ResourceKind
    discovery_backend: Literal["exa_keyless"] = "exa_keyless"
    access: Literal["indexed_reference_only"] = "indexed_reference_only"
    direct_read_status: Literal["not_attempted"] = "not_attempted"
    subject_identity: Literal["unknown"] = "unknown"


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
