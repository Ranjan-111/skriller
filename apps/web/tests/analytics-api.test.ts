import { describe, expect, it, vi } from "vitest";
import { createApi } from "../src/lib/api";
import type { AnalyticsGrant } from "../src/lib/youtube-analytics";

const workspace = "22222222-2222-4222-8222-222222222222";
const grant: AnalyticsGrant = {
  id: "11111111-1111-4111-8111-111111111111",
  workspace_id: workspace,
  created_by: "owner",
  state: "active",
  channel_id: "UC" + "a".repeat(22),
  scopes: [],
  expires_at: "2099-01-01T00:00:00Z",
  access_expires_at: "2099-01-01T00:00:00Z",
  remote_revocation: "not_performed",
};
describe("analytics API contracts", () => {
  it("uses bearer authentication and no-store for metadata and keeps OAuth code out of URLs", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json(grant));
    const api = createApi("http://test", fetcher, async () => "app-token");
    await api.analyticsComplete(
      workspace,
      grant.id,
      "a".repeat(43),
      "private-code",
    );
    const [url, init] = fetcher.mock.calls[0];
    expect(url).not.toContain("private-code");
    expect(init.headers.get("Authorization")).toBe("Bearer app-token");
    expect(init.cache).toBe("no-store");
    expect(JSON.parse(init.body)).toEqual({
      grant_id: grant.id,
      state: "a".repeat(43),
      code: "private-code",
    });
  });
  it.each([
    { ...grant, workspace_id: "other" },
    { ...grant, access_token: "private-sentinel" },
    { ...grant, id: "invalid" },
  ])("rejects malformed or secret-bearing grant metadata", async (value) => {
    const api = createApi(
      "http://test",
      vi.fn().mockResolvedValue(Response.json([value])),
    );
    await expect(api.analyticsGrants(workspace)).rejects.toThrow(
      "Unexpected analytics connection",
    );
  });
  it("rejects a different grant returned by refresh", async () => {
    const api = createApi(
      "http://test",
      vi.fn().mockResolvedValue(
        Response.json({
          ...grant,
          id: "33333333-3333-4333-8333-333333333333",
        }),
      ),
    );
    await expect(api.analyticsRefresh(workspace, grant.id)).rejects.toThrow(
      "Unexpected analytics connection",
    );
  });
  it("does not expose provider/configuration response bodies or research errors", async () => {
    const api = createApi(
      "http://test",
      vi
        .fn()
        .mockResolvedValue(
          Response.json({ detail: "private-sentinel" }, { status: 503 }),
        ),
    );
    await expect(api.analyticsGrants(workspace)).rejects.toThrow(
      "Owner analytics needs server configuration",
    );
    const malformed = createApi(
      "http://test",
      vi.fn().mockResolvedValue(new Response("private-sentinel")),
    );
    await expect(malformed.analyticsGrants(workspace)).rejects.toThrow(
      "Unexpected analytics response",
    );
  });
  it("rejects an authorization link outside the fixed Google consent endpoint", async () => {
    const api = createApi(
      "http://test",
      vi.fn().mockResolvedValue(
        Response.json({
          grant_id: grant.id,
          authorization_url: "https://evil.test/?state=" + "a".repeat(43),
          expires_at: "2099-01-01T00:00:00Z",
        }),
      ),
    );
    await expect(api.analyticsStart(workspace)).rejects.toThrow(
      "consent response is invalid",
    );
  });
  it("accepts literal metrics and rejects substituted channels, units and nonnumeric values", async () => {
    const query = {
      start_date: "2020-01-01",
      end_date: "2020-01-02",
      metrics: ["views"],
    };
    const report = {
      status: "partial",
      grant_id: grant.id,
      channel_id: grant.channel_id,
      ...query,
      timezone: "America/Los_Angeles",
      currency: null,
      coverage_complete: false,
      availability: "provider_returned_days_only",
      summary_status: "literal_metrics_only",
      source_platform: "youtube_analytics",
      collected_at: "2020-01-03T00:00:00Z",
      response_sha256: "a".repeat(64),
      units: { views: "count" },
      unavailable_metrics: {},
      summary: ["42 views"],
      rows: [{ day: "2020-01-01", metrics: { views: 42 } }],
    };
    const api = createApi(
      "http://test",
      vi.fn().mockResolvedValue(Response.json(report)),
    );
    expect(
      (await api.analyticsReport(workspace, grant, query)).rows[0].metrics
        .views,
    ).toBe(42);
    for (const change of [
      { channel_id: "UC" + "b".repeat(22) },
      { units: { views: "seconds" } },
      { rows: [{ day: "2020-01-01", metrics: { views: "42" } }] },
      { rows: [null] },
    ]) {
      const invalid = createApi(
        "http://test",
        vi.fn().mockResolvedValue(Response.json({ ...report, ...change })),
      );
      await expect(
        invalid.analyticsReport(workspace, grant, query),
      ).rejects.toThrow("Unexpected analytics report");
    }
  });
});
