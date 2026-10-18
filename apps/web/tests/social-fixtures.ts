import type { ResearchCandidate, SocialReadView } from "../src/lib/api";
export function socialCandidate(
  source: "instagram" | "facebook",
): ResearchCandidate {
  const instagram = source === "instagram";
  const url = `https://www.${source}.com/synthetic${instagram ? "/" : ""}`;
  const base = {
    source_url: url,
    observed_at: "2026-10-18T00:00:00Z",
    username: "synthetic",
    name: "Synthetic account",
    subject_identity: "unknown" as const,
    coverage_complete: false as const,
  };
  const social_read: SocialReadView = {
    evidence_id: "00000000-0000-4000-8000-000000000062",
    api_requests: instagram ? 1 : 0,
    network_requests_seen: 4,
    resource: instagram
      ? {
          ...base,
          source: "instagram",
          visibility: "public",
          resource_kind: "profile",
          account_kind: "unknown",
          verified: null,
          bio_excerpt: "Synthetic biography",
          followers: null,
          following: 0,
          posts: 3,
          owner_analytics: "unavailable",
        }
      : {
          ...base,
          source: "facebook",
          visibility: "unknown",
          company_identity: "unknown",
          group_access: "unavailable",
          followers_display: "1.2K followers",
          friends_display: null,
        },
  };
  return {
    id: "social1",
    title: "Synthetic account",
    url,
    snippet: "Search reference",
    source,
    provider: instagram ? "opencli_instagram" : "opencli_facebook",
    evidence_kind: "search_reference",
    qualification: "unverified",
    observed_at: base.observed_at,
    provenance: [],
    social_read,
  };
}
