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
  qualification: "unverified",
  observed_at: "2026-10-12T00:00:00Z",
  provenance: [],
};
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("search snippet downloads", () => {
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
    expect(csv).toContain('"evidence_kind","qualification","observed_at"');
    expect(csv).toContain('"search_snippet","unverified"');
  });
  it("JSON preserves source text and exports only the agreed source columns", () => {
    const rows = JSON.parse(
      serializeSources([{ ...candidate, title: "=Raw text" }], "json"),
    );
    expect(rows).toEqual([
      {
        title: "=Raw text",
        url: candidate.url,
        snippet: candidate.snippet,
        source: "web",
        evidence_kind: "search_snippet",
        qualification: "unverified",
        observed_at: candidate.observed_at,
      },
    ]);
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
  expect(name).toBe("skriller-search-snippets.csv");
  expect(href).toBe("blob:test-export");
  expect(create.mock.calls[0][0].type).toBe("text/csv;charset=utf-8");
  expect(document.querySelector("a[download]")).toBeNull();
  expect(revoke).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1000);
  expect(revoke).toHaveBeenCalledWith("blob:test-export");
});
