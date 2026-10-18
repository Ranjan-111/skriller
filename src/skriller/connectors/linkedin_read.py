"""Typed resource reads over the acquired LinkedIn SectionCapture implementation."""

import json
import re
from datetime import datetime
from typing import Literal, cast
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from skriller.connectors.linkedin_discovery import DiscoveryData


class LinkedInRead(DiscoveryData):
    operation: Literal["read_profile", "read_company", "read_post"]
    resource_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")
    post_kind: Literal["activity", "ugcPost"] = "activity"

    @model_validator(mode="after")
    def supported_resource(self):
        if self.operation == "read_post":
            if not re.fullmatch(r"[0-9]{1,30}", self.resource_id):
                raise ValueError("Post resource must be a numeric native ID")
        elif self.post_kind != "activity" or self.resource_id.lower() in {"me", "self"}:
            raise ValueError("An explicit supported resource is required")
        return self

    def target_url(self):
        if self.operation == "read_profile":
            return f"https://www.linkedin.com/in/{self.resource_id}/"
        if self.operation == "read_company":
            return f"https://www.linkedin.com/company/{self.resource_id}/about/"
        return f"https://www.linkedin.com/feed/update/urn:li:{self.post_kind}:{self.resource_id}/"

    def section(self):
        return {"read_profile": "main_profile", "read_company": "about", "read_post": "post"}[
            self.operation
        ]


def request_for_url(url: str) -> LinkedInRead:
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname != "www.linkedin.com"
        or parts.port not in {None, 443}
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ValueError("An explicit canonical LinkedIn reference is required")
    for pattern, operation in (
        (r"/in/([A-Za-z0-9_-]{1,200})/?", "read_profile"),
        (r"/company/([A-Za-z0-9_-]{1,200})(?:/about)?/?", "read_company"),
    ):
        match = re.fullmatch(pattern, parts.path)
        if match:
            return LinkedInRead.model_validate({"operation": operation, "resource_id": match[1]})
    match = re.fullmatch(r"/feed/update/urn:li:(activity|ugcPost):([0-9]{1,30})/?", parts.path)
    if match:
        return LinkedInRead(
            operation="read_post",
            resource_id=match[2],
            post_kind="activity" if match[1] == "activity" else "ugcPost",
        )
    raise ValueError("LinkedIn resource read is unsupported")


class LinkedInReadResult(DiscoveryData):
    source: Literal["linkedin"] = "linkedin"
    evidence_kind: Literal["resource_section_read"] = "resource_section_read"
    resource_kind: Literal["profile", "company", "post"]
    source_url: str
    section: Literal["main_profile", "about", "post"]
    text: str = Field(min_length=1, max_length=16384)
    text_truncated: bool
    observed_at: datetime
    coverage_complete: Literal[False] = False
    subject_identity: Literal["unknown"] = "unknown"
    contact_details: Literal["unavailable"] = "unavailable"
    buying_intent: Literal["not_inferred"] = "not_inferred"

    @model_validator(mode="after")
    def resource_alignment(self):
        request = request_for_url(self.source_url)
        if (
            request.target_url() != self.source_url
            or request.section() != self.section
            or request.operation.removeprefix("read_") != self.resource_kind
            or self.observed_at.tzinfo is None
        ):
            raise ValueError("Resource section metadata does not match its permalink")
        return self


def parse_read_response(payload: dict, request: LinkedInRead, *, observed_at: datetime):
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("An aware observation time is required")
    if (
        not isinstance(payload, dict)
        or len(json.dumps(payload, allow_nan=False).encode()) > 1_048_576
    ):
        raise ValueError("Read output exceeds its bound")
    if payload.get("url") != request.target_url():
        raise ValueError("Read redirected away from the requested resource")
    sections, errors = payload.get("sections"), payload.get("section_errors", {})
    if not isinstance(sections, dict) or set(sections) != {request.section()} or errors:
        raise ValueError("Requested section is unavailable")
    text = sections[request.section()]
    if not isinstance(text, str) or not text.strip():
        raise ValueError("No readable resource section")
    if any(
        marker in text.casefold()
        for marker in (
            "sign in to linkedin",
            "join linkedin to view",
            "security verification",
            "verify you are human",
            "temporarily restricted",
            "authwall",
            "captcha",
            "[rate limited]",
        )
    ):
        raise ValueError("Resource access is blocked")
    return LinkedInReadResult(
        resource_kind=cast(
            Literal["profile", "company", "post"], request.operation.removeprefix("read_")
        ),
        source_url=request.target_url(),
        section=request.section(),
        text=text[:16384],
        text_truncated=len(text) > 16384,
        observed_at=observed_at,
    )
