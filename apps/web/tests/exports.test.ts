import { afterEach, describe, expect, it, vi } from "vitest";
import {
  downloadSources,
  serializeSources,
  SOURCE_EXPORT_LIMIT,
} from "../src/lib/exports";
import type { ResearchCandidate } from "../src/lib/api";
const candidate: ResearchCandidate = {
  id: "private-id",
  title: "Company",
  url: "https://example.com",
  snippet: "A search snippet",
  source: "web",
  provider: "exa_keyless",
  evidence_kind: "search_snippet",
  platform_reference: null,
  qualification: "unverified",
  observed_at: "2026-10-12T00:00:00Z",
  provenance: [
    {
      source: "web",
      original_url: "https://search.example/result/1",
      query: "example company",
      rank: 1,
      provider: "exa_keyless",
      observed_at: "2026-10-12T00:00:00Z",
      evidence_kind: "search_snippet",
    },
  ],
};
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("search snippet downloads", () => {
  it.each(["json", "csv"] as const)(
    "keeps retained Reddit thread bodies out of %s source exports",
    (format) => {
      const source = {
        ...candidate,
        reddit_thread: {
          evidence_id: "00000000-0000-4000-8000-000000000062",
          thread: { comments: [{ text: "private retained comment body" }] },
          signals: [{ quote: "private retained comment body" }],
          rejected_signals: 0,
          signal_coverage_complete: false,
        },
      } as ResearchCandidate;
      const output = serializeSources([source], format);
      expect(output).not.toContain("reddit_thread");
      expect(output).not.toContain("private retained comment body");
    },
  );
  it.each([
    "=SUM(A1)",
    "+123",
    "-123",
    "@SUM(A1)",
    ' \t=HYPERLINK("bad")',
    "\r\n+1",
    "\uFEFF@bad",
  ])("neutralizes spreadsheet formula input %s", (value) => {
    const csv = serializeSources([{ ...candidate, title: value }], "csv");
    expect(csv.split("\r\n")[1].startsWith("\"'")).toBe(true);
    expect(csv).not.toContain('"private-id"');
  });
  it("quotes commas, embedded quotes, and multiline text without losing contents", () => {
    const csv = serializeSources(
      [{ ...candidate, snippet: 'First, "quoted"\nSecond line' }],
      "csv",
    );
    expect(csv).toContain('"First, ""quoted""\nSecond line"');
    expect(csv).toContain(
      '"evidence_kind","platform_reference","qualification","observed_at"',
    );
    expect(csv).toContain('"search_snippet","null","unverified"');
    expect(csv).toContain('"exa_keyless","search_snippet"');
    expect(csv).toContain('"[{""source"":""web""');
  });
  it("JSON preserves source text, provider, evidence kind, and query provenance", () => {
    const rows = JSON.parse(
      serializeSources([{ ...candidate, title: "=Raw text" }], "json"),
    );
    expect(rows).toEqual([
      {
        title: "=Raw text",
        url: candidate.url,
        snippet: candidate.snippet,
        source: "web",
        provider: "exa_keyless",
        evidence_kind: "search_snippet",
        platform_reference: null,
        qualification: "unverified",
        observed_at: candidate.observed_at,
        provenance: candidate.provenance,
      },
    ]);
  });
  it("exports connected reference provenance without rewriting the access claim", () => {
    const reference = {
      source: "linkedin" as const,
      resource_kind: "profile" as const,
      discovery_backend: "linkedin_mcp" as const,
      access: "connected_search_reference_only" as const,
      direct_read_status: "not_attempted" as const,
      subject_identity: "unknown" as const,
    };
    const source: ResearchCandidate = {
      ...candidate,
      source: "linkedin",
      provider: "linkedin_mcp",
      evidence_kind: "search_reference",
      platform_reference: reference,
      provenance: [
        {
          source: "linkedin",
          original_url: "https://www.linkedin.com/in/synthetic-person",
          query: "synthetic researcher",
          rank: 1,
          provider: "linkedin_mcp",
          observed_at: candidate.observed_at,
          evidence_kind: "search_reference",
        },
      ],
    };
    const rows = JSON.parse(serializeSources([source], "json"));
    expect(rows[0]).toMatchObject({
      provider: "linkedin_mcp",
      evidence_kind: "search_reference",
      platform_reference: reference,
      provenance: [
        { provider: "linkedin_mcp", evidence_kind: "search_reference" },
      ],
    });
  });
  it.each(["json", "csv"] as const)(
    "bounds %s export to 100 actual sources",
    (format) => {
      const items = Array.from({ length: 105 }, (_, index) => ({
        ...candidate,
        title: `Unique source ${index}`,
      }));
      const output = serializeSources(items, format);
      expect(output).toContain(`Unique source ${SOURCE_EXPORT_LIMIT - 1}`);
      expect(output).not.toContain(`Unique source ${SOURCE_EXPORT_LIMIT}`);
    },
  );
  it("has a header-only CSV and empty JSON when no candidates exist", () => {
    expect(JSON.parse(serializeSources([], "json"))).toEqual([]);
    expect(serializeSources([], "csv").split("\r\n")).toHaveLength(1);
  });
});

it("downloads a neutral filename and releases the temporary URL", async () => {
  vi.useFakeTimers();
  const create = vi.fn().mockReturnValue("blob:test-export");
  const revoke = vi.fn();
  const NativeURL = URL;
  vi.stubGlobal(
    "URL",
    class extends NativeURL {
      static createObjectURL = create;
      static revokeObjectURL = revoke;
    },
  );
  let name = "";
  let href = "";
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    name = this.download;
    href = this.href;
  });
  downloadSources([candidate], "csv");
  expect(name).toBe("skriller-research-sources.csv");
  expect(href).toBe("blob:test-export");
  expect(create.mock.calls[0][0].type).toBe("text/csv;charset=utf-8");
  expect(document.querySelector("a[download]")).toBeNull();
  expect(revoke).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1000);
  expect(revoke).toHaveBeenCalledWith("blob:test-export");
});

it.each(["json", "csv"] as const)(
  "keeps social retained profile bodies out of %s source exports",
  async (format) => {
    const { socialCandidate } = await import("./social-fixtures");
    const source = socialCandidate("instagram");
    const serialized = serializeSources([source], format);
    expect(serialized).toContain("opencli_instagram");
    expect(serialized).not.toContain("Synthetic biography");
    expect(serialized).not.toContain("social_read");
  },
);
