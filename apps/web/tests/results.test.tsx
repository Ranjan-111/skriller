import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResearchResultsPanel } from "../src/components/research-results";
import * as exports from "../src/lib/exports";
import { createApi } from "../src/lib/api";

const run = {
  id: "j1",
  workspace_id: "w1",
  state: "completed",
  stage: null,
  version: 2,
  terminal_reason: null,
  result_count: 1,
};
const result = {
  job_id: "j1",
  workspace_id: "w1",
  state: "completed",
  limitations: ["No qualification performed."],
  results: [
    {
      id: "r1",
      title: "Acme source",
      url: "https://example.com/",
      snippet: "Public company information",
      source: "web",
      provider: "exa_keyless",
      evidence_kind: "search_snippet",
      qualification: "unverified",
      observed_at: "2026-10-12T00:00:00Z",
      provenance: [
        {
          source: "web",
          original_url: "https://search.example/result/1",
          query: "Aurora Ledger fintech",
          rank: 2,
          provider: "exa_keyless",
          observed_at: "2026-10-12T00:00:00Z",
          evidence_kind: "search_snippet",
        },
      ],
    },
  ],
};
function client() {
  const api = createApi("http://test", vi.fn());
  return {
    ...api,
    job: vi.fn().mockResolvedValue(run),
    results: vi.fn().mockResolvedValue(result),
    plan: vi.fn().mockResolvedValue({
      job_id: "j1",
      plan_id: "p1",
      workspace_id: "w1",
      status: "ready",
      interpretation: {
        schema_version: 1,
        workspace_id: "w1",
        conversation_id: "c1",
        revision: 1,
        entity_type: "person",
        must_have: [
          { field: "location", operator: "contains", value: "Bengaluru" },
        ],
        preferences: [],
        exclusions: [],
        requested_fields: [],
        sources: ["web"],
        freshness_days: null,
        unsupported_criteria: [],
        clarification: null,
        limits: {},
      },
    }),
    usage: vi.fn().mockResolvedValue({
      job_id: "j1",
      workspace_id: "w1",
      currency: "USD",
      budget_cap_usd: "1",
      confirmed_cost_usd: "0.1",
      estimated_cost_usd: "0.2",
      reserved_cost_usd: "0.1",
      exposure_ceiling_usd: "0.4",
      remaining_budget_usd: "0.6",
      dimensions: { confirmed: {}, estimated: {}, reserved: {} },
      stage_metrics: [
        {
          stage: "discovering",
          source: "exa_keyless",
          observations: 1,
          succeeded: 1,
          failed: 0,
          accepted_result_count: 2,
          stage_io_seconds: "2.5",
          confirmed_cost_usd: "0",
          estimated_cost_usd: "0",
          unpriced_observations: 0,
        },
      ],
      invalid_stage_observations: 0,
      stage_metrics_truncated: false,
    }),
  };
}
afterEach(() => vi.useRealTimers());
describe("actual research results", () => {
  it("shows saved-page quotes as unverified and escapes source markup", async () => {
    const api = client();
    api.results.mockResolvedValue({
      ...result,
      results: [
        {
          ...result.results[0],
          collection: { status: "read", failure_code: null },
          extraction: {
            status: "observed",
            failure_code: null,
            coverage_complete: false,
            rejected_claims: 2,
            omitted_chunks: 1,
            observations: [
              {
                claim_id: "c1",
                field: "company_name",
                value: "Aurora Ledger",
                quote: '<script>alert("source")</script>',
                status: "unverified",
              },
            ],
          },
        },
      ],
    });
    const { container } = render(
      <ResearchResultsPanel
        api={api}
        job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
      />,
    );
    const summary = await screen.findByText(
      "Page observations (1) · Unverified",
    );
    fireEvent.click(summary);
    expect(screen.getByText("company name: Aurora Ledger")).toBeVisible();
    expect(screen.getByText('<script>alert("source")</script>')).toBeVisible();
    expect(
      screen.getByText("2 unsupported model drafts were rejected."),
    ).toBeVisible();
    expect(
      screen.getByText(
        "Part of the page was outside this run’s extraction coverage.",
      ),
    ).toBeVisible();
    expect(container.querySelector("script")).toBeNull();
  });
  it("stops an active scoped run and refreshes its actual terminal state", async () => {
    const api = client();
    api.job.mockResolvedValue({ ...run, state: "running" });
    api.cancel = vi.fn().mockImplementation(async () => {
      api.job.mockResolvedValue({
        ...run,
        state: "cancelled",
        terminal_reason: "user_cancelled",
      });
    });
    render(
      <ResearchResultsPanel
        api={api}
        job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Stop research" }),
    );
    expect(
      await screen.findByRole("heading", { name: "Research cancelled" }),
    ).toBeVisible();
    expect(api.cancel).toHaveBeenCalledWith("j1", "w1");
    expect(
      screen.queryByRole("button", { name: "Stop research" }),
    ).not.toBeInTheDocument();
  });
  it("renders fetched sources as unverified snippets with safe original links", async () => {
    const api = client();
    render(
      <ResearchResultsPanel
        api={api}
        job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
      />,
    );
    expect(
      await screen.findByRole("heading", { name: "Research complete" }),
    ).toBeVisible();
    const link = await screen.findByRole("link", { name: /Acme source/ });
    expect(link).toHaveAttribute("href", "https://example.com/");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText("web · Search snippet · Unverified")).toBeVisible();
    expect(await screen.findByText("What this run understood")).toBeVisible();
    expect(screen.getByText("location contains Bengaluru")).toBeVisible();
    expect(screen.getByText("No qualification performed.")).toBeVisible();
    fireEvent.click(await screen.findByText("Search references (1)"));
    expect(screen.getByText(/do not mean the page was read/)).toBeVisible();
    expect(
      screen.getByRole("link", { name: /Open search reference/ }),
    ).toHaveAttribute("href", "https://search.example/result/1");
    expect(api.job).toHaveBeenCalledWith("j1", "w1", expect.any(AbortSignal));
    expect(api.results).toHaveBeenCalledTimes(1);
    expect(api.plan).toHaveBeenCalledWith("j1", "w1", expect.any(AbortSignal));
  });
  it("never links script addresses or credential-bearing URLs", async () => {
    const api = client();
    api.results.mockResolvedValue({
      ...result,
      results: result.results.map((item) => ({
        ...item,
        url: "javascript:alert(1)",
        snippet: "<script>bad()</script>",
      })),
    });
    render(
      <ResearchResultsPanel api={api} job={{ id: "j1", status: "accepted" }} />,
    );
    expect(await screen.findByText(/Source link unavailable/)).toBeVisible();
    expect(
      screen
        .getAllByRole("link")
        .every((link) => link.getAttribute("href")?.startsWith("https://")),
    ).toBe(true);
    expect(
      screen.queryByRole("link", { name: /Acme source/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("<script>bad()</script>")).toBeVisible();
    expect(document.querySelector("script")).toBeNull();
  });
  it("checks queued runs again, then stops polling once complete", async () => {
    vi.useFakeTimers();
    const api = client();
    api.job.mockResolvedValueOnce({ ...run, state: "queued", result_count: 0 });
    api.results.mockResolvedValueOnce({
      ...result,
      state: "queued",
      results: [],
    });
    render(
      <ResearchResultsPanel api={api} job={{ id: "j1", status: "accepted" }} />,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(
      screen.getByRole("heading", { name: "Research queued" }),
    ).toBeVisible();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(
      screen.getByRole("heading", { name: "Research complete" }),
    ).toBeVisible();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(api.job).toHaveBeenCalledTimes(2);
  });
  it("reports polling failures with a manual retry rather than a fabricated result", async () => {
    const api = client();
    api.job.mockRejectedValueOnce(new Error("Connection lost"));
    render(
      <ResearchResultsPanel api={api} job={{ id: "j1", status: "accepted" }} />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Connection lost",
    );
    expect(api.results).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Check run again" }));
    expect(
      await screen.findByRole("link", { name: /Acme source/ }),
    ).toBeVisible();
  });
  it("aborts outstanding polling when the run view is dismissed", async () => {
    const api = client();
    api.job.mockReturnValue(new Promise(() => {}));
    const view = render(
      <ResearchResultsPanel api={api} job={{ id: "j1", status: "accepted" }} />,
    );
    const signal = api.job.mock.calls[0][2] as AbortSignal;
    view.unmount();
    expect(signal.aborted).toBe(true);
  });
  it("keeps partial sources visible and states that requests could not finish", async () => {
    const api = client();
    api.job.mockResolvedValue({ ...run, state: "partial" });
    render(
      <ResearchResultsPanel api={api} job={{ id: "j1", status: "accepted" }} />,
    );
    expect(
      await screen.findByRole("heading", { name: /partial results/ }),
    ).toBeVisible();
    expect(
      await screen.findByRole("link", { name: /Acme source/ }),
    ).toBeVisible();
    expect(
      screen.getByText(/Some source requests could not finish/),
    ).toBeVisible();
  });
  it("offers checkpoint-guarded resume for a paused run and refreshes its state", async () => {
    const api = client();
    api.job.mockResolvedValueOnce({ ...run, state: "paused", result_count: 1 });
    api.resume = vi.fn().mockImplementation(async () => {
      api.job.mockResolvedValue({ ...run, state: "queued", result_count: 1 });
    });
    render(
      <ResearchResultsPanel
        api={api}
        job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
      />,
    );
    expect(
      await screen.findByRole("heading", { name: "Research paused" }),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Resume research" }));
    expect(
      await screen.findByRole("heading", { name: "Research queued" }),
    ).toBeVisible();
    expect(api.resume).toHaveBeenCalledWith("j1", "w1");
  });
  it("shows truthful source access scope without claiming credential validation", async () => {
    const api = client();
    api.sourceDiagnostics = vi.fn().mockResolvedValue([
      {
        capability: {
          source: "linkedin",
          operation: "discover",
          engineering_status: "tested",
          operational_status: "experimental",
          auth_kind: "none",
          access_route: "Exa keyless public indexed references",
          version: "exa_keyless_v1",
          allowed_fields: ["title", "url", "snippet"],
        },
        disabled: false,
        setup_state: "experimental",
        evidence_scope: "public_indexed_references",
        credential_validation: "not_performed",
      },
    ]);
    render(
      <ResearchResultsPanel
        api={api}
        job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Check source readiness" }),
    );
    expect(
      await screen.findByText(
        /public search references; not direct platform access/i,
      ),
    ).toBeVisible();
    expect(
      screen.getByText(/does not test credentials or sign in to a platform/i),
    ).toBeVisible();
  });
  it("shows confirmed, uncertain and reserved cost separately", async () => {
    const api = client();
    render(
      <ResearchResultsPanel
        api={api}
        job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Show run usage and budget" }),
    );
    expect(await screen.findByText("Confirmed cost")).toBeVisible();
    expect(
      await screen.findByRole("heading", { name: "Work by stage" }),
    ).toBeVisible();
    expect(screen.getByText(/1 succeeded \/ 1 observed/)).toBeVisible();
    expect(screen.getByText("Confirmed cost").parentElement).toHaveTextContent(
      "0.1 USD",
    );
    expect(screen.getByText("Uncertain estimate")).toBeVisible();
    expect(screen.getByText(/not final provider invoices/)).toBeVisible();
    expect(api.usage).toHaveBeenCalledWith("j1", "w1");
  });
});

it("downloads displayed source snippets through both explicit export actions", async () => {
  const download = vi
    .spyOn(exports, "downloadSources")
    .mockImplementation(() => {});
  const api = client();
  render(
    <ResearchResultsPanel api={api} job={{ id: "j1", status: "accepted" }} />,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Download snippets as JSON" }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Download snippets as CSV" }),
  );
  expect(download.mock.calls).toEqual([
    [result.results, "json"],
    [result.results, "csv"],
  ]);
  download.mockRestore();
});
