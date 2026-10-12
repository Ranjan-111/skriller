"""Conservative candidate URL identity around the copied Agent-Reach URL guards.

Only explicitly known tracking parameters are removed. Names are never identity
keys, and meaningful query/fragment/native IDs remain distinct.
"""

from dataclasses import dataclass, field
from hashlib import sha256
from urllib.parse import unquote_plus, urlsplit, urlunsplit

from agent_reach.utils.url import domain_matches, normalize_public_http_url

from skriller.connectors.search import SearchHit, SearchPage

TRACKING = frozenset({"gclid", "fbclid", "msclkid", "dclid"})


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

    @property
    def identity_hash(self) -> str:
        return sha256(self.canonical_url.encode()).hexdigest()


def deduplicate(pages: list[tuple[str, SearchPage]], *, limit: int = 100) -> list[Candidate]:
    if isinstance(limit, bool) or not 1 <= limit <= 100 or len(pages) > 20:
        raise ValueError("Candidate set exceeds supported bounds")
    candidates: dict[str, Candidate] = {}
    for source, page in pages:
        for hit in page.hits:
            identity = canonical_url(hit.url)
            if identity not in candidates:
                if len(candidates) >= limit:
                    continue
                candidates[identity] = Candidate(identity, hit)
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
