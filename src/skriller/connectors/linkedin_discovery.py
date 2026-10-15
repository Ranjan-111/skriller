"""Read-only search contracts using the pinned LinkedIn backend's URL grammar.

Only already-returned backend data is adapted here. Parsing does not start a
browser, import cookies, bind a connection or verify an operation as ready.
"""

import json
from datetime import datetime
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from agent_reach.utils.url import host_matches, normalize_public_http_url
from pydantic import BaseModel, ConfigDict, Field, model_validator

from skriller._vendor.linkedin.link_metadata import Reference, classify_link, dedupe_references
from skriller._vendor.linkedin.search_urls import build_content_search_url, build_people_search_url


class DiscoveryData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class LinkedInSearch(DiscoveryData):
    operation: Literal["search_people", "search_posts"]
    keywords: str = Field(min_length=1, max_length=500, pattern=r"\S")
    location: str | None = Field(default=None, min_length=1, max_length=200)
    network: list[Literal["F", "S", "O"]] | None = Field(default=None, max_length=3)
    current_company: str | None = Field(default=None, pattern=r"^[0-9]{1,30}$")
    date_posted: Literal["past_24_hours", "past_week", "past_month"] | None = None

    @model_validator(mode="after")
    def operation_filters(self):
        if self.operation == "search_people" and self.date_posted is not None:
            raise ValueError("People search does not support post recency")
        if self.operation == "search_posts" and any(
            value is not None for value in (self.location, self.network, self.current_company)
        ):
            raise ValueError("Post search does not support people filters")
        return self

    def backend_arguments(self):
        if self.operation == "search_posts":
            return {"keywords": self.keywords, "date_posted": self.date_posted, "max_pages": 1}
        return {
            "keywords": self.keywords,
            "location": self.location,
            "network": self.network,
            "current_company": self.current_company,
        }

    def search_url(self):
        if self.operation == "search_posts":
            return build_content_search_url(self.keywords, self.date_posted)
        return build_people_search_url(
            self.keywords,
            self.location,
            [str(item) for item in self.network] if self.network is not None else None,
            self.current_company,
        )


class LinkedInReference(DiscoveryData):
    kind: Literal["person", "company", "feed_post", "job"]
    url: str
    label: str | None
    subject_identity: Literal["unknown"] = "unknown"


class LinkedInDiscoveryPage(DiscoveryData):
    backend: Literal["linkedin_mcp"] = "linkedin_mcp"
    status: Literal["parsed_not_live_verified", "partial_not_live_verified"]
    request: LinkedInSearch
    source_url: str
    text: str
    text_truncated: bool
    references: tuple[LinkedInReference, ...]
    failed_sections: tuple[str, ...]
    rejected_count: int
    pagination_supported: Literal[False] = False
    observed_at: datetime


def parse_search_response(
    payload: dict, request: LinkedInSearch, *, observed_at: datetime
) -> LinkedInDiscoveryPage:
    """References remain unaligned links, never invented post-author relations."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("An aware observation time is required")
    if len(json.dumps(payload, allow_nan=False).encode()) > 1_048_576:
        raise ValueError("LinkedIn search response exceeds bounds")
    url = normalize_public_http_url(payload.get("url", ""))
    expected, actual = urlsplit(request.search_url()), urlsplit(url)
    if (
        not host_matches(url, "linkedin.com")
        or actual.path != expected.path
        or parse_qs(actual.query) != parse_qs(expected.query)
        or actual.fragment
    ):
        raise ValueError("Backend search URL does not preserve requested filters")
    sections = payload.get("sections")
    if not isinstance(sections, dict) or not isinstance(sections.get("search_results"), str):
        raise TypeError("Missing search results section")
    text = sections["search_results"]
    errors = payload.get("section_errors", {})
    if (
        not isinstance(errors, dict)
        or len(errors) > 10
        or any(not isinstance(key, str) or len(key) > 80 for key in errors)
    ):
        raise ValueError("Invalid search section diagnostics")
    if not text.strip():
        # Backend shell/login/empty extraction is not proof of zero matches.
        raise ValueError("Search returned no readable section")
    refs = payload.get("references", {})
    if not isinstance(refs, dict):
        raise TypeError("Invalid search references")
    rows = refs.get("search_results", [])
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("Search reference bounds exceeded")
    accepted: list[Reference] = []
    rejected = 0
    for raw in rows:
        if not isinstance(raw, dict) or not isinstance(raw.get("url"), str):
            rejected += 1
            continue
        try:
            reference_url = normalize_public_http_url(raw["url"])
            normalized = classify_link(reference_url)
            if (
                not host_matches(reference_url, "linkedin.com")
                or normalized is None
                or normalized[0] not in {"person", "company", "feed_post", "job"}
                or raw.get("kind") != normalized[0]
                or raw.get("text") is not None
                and not isinstance(raw["text"], str)
            ):
                raise ValueError("Unsupported search reference")
            entry: Reference = {"kind": normalized[0], "url": normalized[1]}
            if raw.get("text"):
                entry["text"] = raw["text"][:300]
            accepted.append(entry)
        except ValueError:
            rejected += 1
    normalized_refs = dedupe_references(accepted, cap=25)
    return LinkedInDiscoveryPage(
        status="partial_not_live_verified" if errors else "parsed_not_live_verified",
        request=request,
        source_url=url,
        text=text[:16384],
        text_truncated=len(text) > 16384,
        references=tuple(
            LinkedInReference.model_validate(
                {"kind": row["kind"], "url": row["url"], "label": row.get("text")}
            )
            for row in normalized_refs
        ),
        failed_sections=tuple(sorted(errors)),
        rejected_count=rejected,
        observed_at=observed_at,
    )
