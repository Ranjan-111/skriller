"""Product native-ID tokens must explicitly identify their platform object kind.

Trusted adapters/reviewers normalize identifiers to ``kind:opaque_id``. A URL,
handle, or post ID never supplies a person's identifier through this contract.
This is a product representation, not a parser for arbitrary platform URNs.
"""

import re
from typing import get_args

from skriller.contracts import Source


def native_identity_value(kind: str, field: str, value: str) -> str | None:
    if kind not in {"person", "company", "post", "video", "community"}:
        return None
    if field not in {f"native_id.{source}" for source in get_args(Source)}:
        return None
    # Public web/RSS references have no platform-native object identity.
    if field in {"native_id.web", "native_id.rss"}:
        return None
    if not re.fullmatch(r"(?:person|company|post|video|community):[A-Za-z0-9_.-]{1,180}", value):
        return None
    return value if value.split(":", 1)[0] == kind else None
