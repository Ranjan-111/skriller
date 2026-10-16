import { describe, expect, it, vi } from "vitest";
import { createApi } from "../src/lib/api";
import { crmConsentState } from "../src/lib/crm";

const workspace = "22222222-2222-4222-8222-222222222222";
const job = "11111111-1111-4111-8111-111111111111";
const destination = { id: job, instance_url: "https://acme.my.salesforce.com", enabled: true, expires_at: "2099-01-01T00:00:00Z", generation: 1 };
const report = { status: "partial", coverage_complete: false, expansion_status: "unavailable", inference_status: "unavailable", inferences: [], supplied_evidence_count: 1, used_evidence_count: 1, unknowns: [], observations: [{ evidence_id: "evidence-1", quote: "42 views", source_url: "https://youtube.com/channel", source_platform: "youtube_analytics", collected_at: "2020-01-01T00:00:00Z", excerpt_sha256: "a".repeat(64), stored_content_sha256: null, qualification: "source_statement_not_independently_verified", content_hash_status: "stored_metadata_not_revalidated" }] };
describe("private analytics jobs and Salesforce connection contracts", () => {
  it("sends a stable idempotency key in the authenticated summary request", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ job_id: job, state: "queued", summary_state: "queued", result: null }));
    const api = createApi("http://test", fetcher, async () => "token");
    const result = await api.analyticsSummaryStart(workspace, { id: job } as never, { start_date: "2020-01-01", end_date: "2020-01-02", metrics: ["views"] }, "stable-key");
    expect(result.job_id).toBe(job);
    expect(fetcher.mock.calls[0][1].headers.get("Idempotency-Key")).toBe("stable-key");
    expect(fetcher.mock.calls[0][1].headers.get("Authorization")).toBe("Bearer token");
  });
  it("accepts only provenance-bearing HTTPS observations and exact job IDs", async () => {
    const api = createApi("http://test", vi.fn().mockResolvedValue(Response.json({ job_id: job, state: "completed", summary_state: "completed", result: report })));
    expect((await api.analyticsSummaryGet(workspace, job)).result?.observations[0].evidence_id).toBe("evidence-1");
    const invalid = createApi("http://test", vi.fn().mockResolvedValue(Response.json({ job_id: job, state: "completed", summary_state: "completed", result: { ...report, observations: [{ ...report.observations[0], source_url: "javascript:alert(1)" }] } })));
    await expect(invalid.analyticsSummaryGet(workspace, job)).rejects.toThrow("Unexpected private summary");
  });
  it("validates Salesforce PKCE destination, response origin, and strict owner metadata", async () => {
    const url = new URL("https://login.salesforce.com/services/oauth2/authorize");
    url.searchParams.set("response_type", "code"); url.searchParams.set("code_challenge_method", "S256"); url.searchParams.set("redirect_uri", "http://localhost:3000/connections/salesforce/callback"); url.searchParams.set("state", "a".repeat(43));
    expect(crmConsentState({ consent_id: job, authorization_url: url.href, expires_at: "2099-01-01T00:00:00Z" }, "http://localhost:3000")).toBe("a".repeat(43));
    const api = createApi("http://test", vi.fn().mockResolvedValue(Response.json([destination])), async () => "token");
    await expect(api.crmDestinations(workspace)).resolves.toEqual([destination]);
    const malformed = createApi("http://test", vi.fn().mockResolvedValue(Response.json([{ ...destination, access_token: "secret" }])));
    await expect(malformed.crmDestinations(workspace)).rejects.toThrow("Unexpected Salesforce");
  });
});
