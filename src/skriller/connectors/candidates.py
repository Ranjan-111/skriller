"""Conservative candidate URL identity around the copied Agent-Reach URL guards.

Only explicitly known tracking parameters are removed. Names are never identity
keys, and meaningful query/fragment/native IDs remain distinct.
"""

import json
import re
from dataclasses import dataclass, field
from hashlib import sha256
from urllib.parse import unquote_plus, urlsplit, urlunsplit

from agent_reach.utils.url import domain_matches, normalize_public_http_url

from skriller.connectors.search import SearchHit, SearchPage

TRACKING = frozenset({"gclid", "fbclid", "msclkid", "dclid"})


def native_reference(url: str) -> dict[str, str] | None:
    """URL resource identity only; never establishes an account/person identity.

    Copied Agent-Reach guards validate the host. Unknown shapes, meaningful query
    contexts, fragments and vanity/profile names retain ordinary URL identity.
    These bounded permalink shapes are product glue, not a new source reader.
    """
    if len(url) > 4096:
        raise ValueError("URL exceeds candidate bound")
    parsed = urlsplit(normalize_public_http_url(url))
    if parsed.query or parsed.fragment:
        return None
    host = parsed.hostname
    path = parsed.path
    if host in {
        "reddit.com",
        "www.reddit.com",
        "old.reddit.com",
        "new.reddit.com",
        "np.reddit.com",
    }:
        match = re.fullmatch(
            r"/(?:r/[A-Za-z0-9_]{1,32}/)?comments/([a-z0-9]{3,13})"
            r"(?:/[^/]+(?:/([a-z0-9]{3,13}))?)?/?",
            path,
        )
        if match:
            return {
                "namespace": "reddit_comment" if match[2] else "reddit_post",
                "id": match[2] or match[1],
            }
    if host == "redd.it" and re.fullmatch(r"/[a-z0-9]{3,13}/?", path):
        return {"namespace": "reddit_post", "id": path.strip("/")}
    if host in {"linkedin.com", "www.linkedin.com"}:
        match = re.fullmatch(r"/feed/update/urn:li:(activity|ugcPost):([0-9]{1,30})/?", path)
        if match:
            return {
                "namespace": "linkedin_activity" if match[1] == "activity" else "linkedin_ugc_post",
                "id": match[2],
            }
        match = re.fullmatch(r"/posts/[^/]+-activity-([0-9]{1,30})-[A-Za-z0-9_-]{1,32}/?", path)
        if match:
            return {"namespace": "linkedin_activity", "id": match[1]}
    return None


def canonical_url(value: str) -> str:
    if len(value) > 4096:
        raise ValueError("URL exceeds candidate bound")
    parsed = urlsplit(normalize_public_http_url(value))
    host = (parsed.hostname or "").lower().rstrip(".")
    authority = f"[{host}]" if ":" in host else host
    if parsed.port and (parsed.scheme.lower(), parsed.port) not in {("https", 443), ("http", 80)}:
        authority += f":{parsed.port}"
    parts = []
    for part in parsed.query.split("&"):
        key = unquote_plus(part.split("=", 1)[0]).lower()
        if key in TRACKING or key.startswith("utm_"):
            continue
        if domain_matches(host, "linkedin.com") and key in {"trk", "trackingid"}:
            continue
        if part:
            parts.append(part)
    return urlunsplit(
        (parsed.scheme.lower(), authority, parsed.path or "/", "&".join(parts), parsed.fragment)
    )


@dataclass
class Candidate:
    canonical_url: str
    hit: SearchHit
    provenance: list[dict] = field(default_factory=list)
    native_id: dict[str, str] | None = None

    @property
    def identity_hash(self) -> str:
        identity = (
            json.dumps(self.native_id, sort_keys=True) if self.native_id else self.canonical_url
        )
        return sha256(identity.encode()).hexdigest()


def deduplicate(pages: list[tuple[str, SearchPage]], *, limit: int = 100) -> list[Candidate]:
    if isinstance(limit, bool) or not 1 <= limit <= 100 or len(pages) > 20:
        raise ValueError("Candidate set exceeds supported bounds")
    candidates: dict[str, Candidate] = {}
    for source, page in pages:
        for hit in page.hits:
            url = canonical_url(hit.url)
            candidate = Candidate(url, hit, native_id=native_reference(url))
            identity = candidate.identity_hash
            if identity not in candidates:
                if len(candidates) >= limit:
                    continue
                candidates[identity] = candidate
            provenance = {
                "source": source,
                "original_url": hit.url,
                "query": page.query,
                "rank": hit.rank,
                "provider": hit.provider,
                "observed_at": page.observed_at.isoformat(),
                "evidence_kind": hit.evidence_kind,
            }
            if provenance not in candidates[identity].provenance:
                candidates[identity].provenance.append(provenance)
    return list(candidates.values())
