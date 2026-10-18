"""Copied Scrapling parse_retry_after without importing its browser/spider stack.

Source: third_party/scrapling/scrapling/spiders/throttle.py (pinned vendored tree).
Function body is unchanged; imports adapted to standard-library equivalents.
License: third_party/scrapling/LICENSE.
"""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Mapping, Optional
import logging

log = logging.getLogger(__name__)

def parse_retry_after(headers: Mapping[str, str]) -> Optional[float]:
    """Return how many seconds a `Retry-After` header asks us to wait, or `None` when it's missing or unreadable.

    :param headers: The response headers to look the value up in.
    """
    value = next((headers[key] for key in headers if key.lower() == "retry-after"), "").strip()
    if not value:
        return None

    try:
        return max(float(value), 0.0)
    except ValueError:
        pass

    try:  # The header can be an HTTP date instead of a number of seconds
        return max((parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds(), 0.0)
    except (TypeError, ValueError):
        log.debug(f"Ignoring an unreadable `Retry-After` header: {value!r}")
        return None
