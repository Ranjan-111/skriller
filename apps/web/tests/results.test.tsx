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
    identityReviews: vi.fn().mockResolvedValue([]),
    identityReview: vi.fn(),
    changeIdentityReview: vi.fn(),
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
          outcomes: { succeeded: 1 },
          correlated_attempt_observations: 1,
          queue_wait_seconds: "0.08",
          queue_wait_samples: 1,
          collection_timings: {
            observations: 1,
            network_seconds: "1.25",
            network_samples: 1,
            parser_seconds: "0.2",
            parser_samples: 1,
            browser_seconds: null,
            browser_samples: 0,
          },
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
          collection: {
            status: "read",
            failure_code: null,
            network_seconds: 0.25,
            parser_seconds: 0.04,
            browser_seconds: 0.5,
          },
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
      "Source observations (1) · Unverified",
    );
    fireEvent.click(summary);
    expect(screen.getByText("company name: Aurora Ledger")).toBeVisible();
    expect(
      screen.getByText("Network 0.25s · Parser 0.04s · Browser 0.50s"),
    ).toBeVisible();
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
  it("groups conflicting observations by field without choosing a winner", async () => {
    const api = client();
    api.results.mockResolvedValue({
      ...result,
      results: [
        {
          ...result.results[0],
          extraction: {
            status: "observed",
            failure_code: null,
            coverage_complete: true,
            rejected_claims: 0,
            omitted_chunks: 0,
            observations: [
              {
                claim_id: "c1",
                field: "current_role",
                value: "Founder",
                quote: "Founder",
                status: "conflict",
                evidence_ids: ["60000000-0000-4000-8000-000000000001"],
              },
              {
                claim_id: "c2",
                field: "current_role",
                value: "Advisor",
                quote: "Advisor",
                status: "conflict",
                evidence_ids: ["60000000-0000-4000-8000-000000000002"],
              },
            ],
          },
        },
      ],
    });
    render(
      <ResearchResultsPanel
        api={api}
        job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
      />,
    );
    fireEvent.click(
      await screen.findByText("Source observations (2) · Unverified"),
    );
    expect(
      screen.getByText(
        "Sources disagree on these fields. No value has been selected as correct.",
      ),
    ).toBeVisible();
    expect(screen.getAllByText("Founder")).toHaveLength(2);
    expect(screen.getAllByText("Advisor")).toHaveLength(2);
    expect(screen.getAllByText("current role")).toHaveLength(1);
    api.evidenceCitation = vi.fn().mockResolvedValue({
      id: "60000000-0000-4000-8000-000000000001",
      source_url: "https://example.org/team",
      source_platform: "web",
      excerpt: "Founder at the company",
      excerpt_truncated: false,
      collected_at: "2026-10-14T00:00:00Z",
      expires_at: null,
      content_hash: null,
      content_hash_status: "stored_metadata_not_revalidated",
    });
    fireEvent.click(
      screen.getAllByRole("button", { name: "View supporting source" })[0],
    );
    expect(await screen.findByText("Founder at the company")).toBeVisible();
    expect(
      screen.getByRole("link", { name: /Open original source/ }),
    ).toHaveAttribute("href", "https://example.org/team");
  });
  it("labels an anonymous discussion reference without creating an author lead", async () => {
    const api = client();
    api.results.mockResolvedValue({
      ...result,
      results: [
        {
          ...result.results[0],
          discussion: {
            resource_kind: "post",
            evidence_kind: "indexed_reference",
            author_handle: null,
            author_identity: "unknown",
          },
        },
      ],
    });
    render(
      <ResearchResultsPanel
        api={api}
        job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
      />,
    );
    expect(await screen.findByText("Discussion post reference")).toBeVisible();
    expect(screen.getByText(/author identity is unknown/)).toBeVisible();
  });
  it.each([
    ["linkedin", "profile", "LinkedIn profile · indexed reference"],
    ["reddit", "comment", "Reddit comment · indexed reference"],
  ] as const)(
    "explains %s %s references without claiming a direct read",
    async (source, resourceKind, heading) => {
      const api = client();
      api.results.mockResolvedValue({
        ...result,
        results: [
          {
            ...result.results[0],
            platform_reference: {
              source,
              resource_kind: resourceKind,
              discovery_backend: "exa_keyless",
              access: "indexed_reference_only",
              direct_read_status: "not_attempted",
              subject_identity: "unknown",
            },
          },
        ],
      });
      render(
        <ResearchResultsPanel
          api={api}
          job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
        />,
      );
      expect(
        await screen.findByRole("region", {
          name: "Platform reference status",
        }),
      ).toBeVisible();
      expect(screen.getByRole("heading", { name: heading })).toBeVisible();
      expect(
        screen.getByText(/A direct platform read was not attempted/),
      ).toBeVisible();
      expect(screen.getByText(/identity is unverified/)).toBeVisible();
      if (resourceKind === "comment")
        expect(screen.getByText(/The author is unknown/)).toBeVisible();
    },
  );
  it("lets owners approve and reverse a suggested identity link", async () => {
    const api = client();
    const suggestion = {
      id: "10000000-0000-4000-8000-000000000001",
      source_id: "20000000-0000-4000-8000-000000000001",
      target_id: "30000000-0000-4000-8000-000000000001",
      state: "suggestion" as const,
      reason: "Matching verified company domain and legal name.",
      review_outcome: null,
    };
    api.identityReviews.mockResolvedValue([suggestion]);
    const subject = (id: string) => ({
      id,
      display_name: "Synthetic company",
      kind: "company",
      available: true,
      context_complete: true,
      identity_facts: [
        {
          claim_id: "40000000-0000-4000-8000-000000000001",
          field: "domain",
          value: "example.org",
          evidence: [
            {
              id: "50000000-0000-4000-8000-000000000001",
              source_url: "https://example.org/about",
              source_platform: "web",
              collected_at: "2026-10-14T00:00:00Z",
              expires_at: null,
              excerpt: "Official company domain: example.org",
              excerpt_truncated: false,
            },
          ],
        },
      ],
    });
    api.identityReview.mockResolvedValue({
      ...suggestion,
      eligible: true,
      can_review: true,
      current_reason: "corroborated_company_domain",
      source: subject(suggestion.source_id),
      target: subject(suggestion.target_id),
    });
    api.changeIdentityReview.mockImplementation(
      async (_workspace, _id, action) => ({
        ...suggestion,
        state: action === "approve" ? "linked" : "reversed",
      }),
    );
    render(
      <ResearchResultsPanel
        api={api}
        job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
      />,
    );
    fireEvent.click(await screen.findByText("Identity review queue"));
    expect(
      screen.queryByRole("button", { name: "Approve link" }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      await screen.findByRole("button", {
        name: "View current identity evidence",
      }),
    );
    expect(
      await screen.findAllByText("Official company domain: example.org"),
    ).toHaveLength(2);
    fireEvent.click(
      await screen.findByRole("button", { name: "Approve link" }),
    );
    expect(
      await screen.findByRole("button", { name: "Reverse link" }),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Reverse link" }));
    expect(await screen.findByText("reversed")).toBeVisible();
    expect(api.changeIdentityReview).toHaveBeenNthCalledWith(
      1,
      "w1",
      suggestion.id,
      "approve",
      expect.any(AbortSignal),
    );
    expect(api.changeIdentityReview).toHaveBeenNthCalledWith(
      2,
      "w1",
      suggestion.id,
      "reverse",
      expect.any(AbortSignal),
    );
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
  it("shows qualification groups, criterion reasons and scoped supporting excerpts", async () => {
    const api = client();
    const evidenceId = "00000000-0000-4000-8000-000000000001";
    api.results.mockResolvedValue({
      ...result,
      groups: {
        confirmed: [],
        near_match: ["r1"],
        excluded: [],
        unverified: [],
      },
      results: [
        {
          ...result.results[0],
          fit: {
            status: "near_match",
            limitations: ["Subject identity needs confirmation."],
            preference_score: 1,
            essential: [
              {
                criterion: {
                  field: "location",
                  operator: "contains",
                  value: "Bengaluru",
                },
                outcome: "unknown",
                reason: "The retained page does not state a location.",
                evidence_ids: [evidenceId],
              },
            ],
            exclusions: [],
            preferences: [
              {
                criterion: {
                  field: "company_type",
                  operator: "contains",
                  value: "fintech",
                },
                outcome: "matched",
                reason:
                  "The source describes the company as a fintech provider.",
                evidence_ids: [evidenceId],
              },
            ],
          },
        },
      ],
    });
    api.evidenceCitation = vi.fn().mockResolvedValue({
      id: evidenceId,
      source_url: "https://example.com/about",
      source_platform: "web",
      collected_at: "2026-10-12T00:00:00Z",
      expires_at: "2026-10-19T00:00:00Z",
      excerpt: "We are based in Bengaluru.",
      excerpt_truncated: true,
      content_hash: null,
      content_hash_status: "stored_metadata_not_revalidated",
    });
    render(
      <ResearchResultsPanel
        api={api}
        job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
      />,
    );
    expect(await screen.findByText("Needs review (1)")).toBeVisible();
    fireEvent.click(screen.getByText("Needs review (1)"));
    fireEvent.click(
      await screen.findByText(/Some required details are unknown/),
    );
    expect(
      screen.getByText("The retained page does not state a location."),
    ).toBeVisible();
    expect(
      screen.getByText(/not be verified from current retained evidence/),
    ).toBeVisible();
    fireEvent.click(
      screen.getAllByRole("button", { name: "View supporting source" })[0],
    );
    expect(await screen.findByText(/We are based in Bengaluru/)).toBeVisible();
    expect(screen.getByText(/Collected/)).toBeVisible();
    expect(
      screen.getByText(/stored metadata and has not been revalidated/),
    ).toBeVisible();
    expect(screen.getByText(/Preferences affect ordering only/)).toBeVisible();
    expect(api.evidenceCitation).toHaveBeenCalledWith(
      "j1",
      evidenceId,
      "w1",
      expect.any(AbortSignal),
    );
  });
  it("explains when a requested criterion citation has expired or was removed", async () => {
    const api = client();
    const evidenceId = "00000000-0000-4000-8000-000000000002";
    api.results.mockResolvedValue({
      ...result,
      results: [
        {
          ...result.results[0],
          fit: {
            status: "near_match",
            limitations: [],
            preference_score: 0,
            essential: [
              {
                criterion: {
                  field: "location",
                  operator: "contains",
                  value: "Bengaluru",
                },
                outcome: "unknown",
                reason: "Not in retained facts.",
                evidence_ids: [evidenceId],
              },
            ],
            exclusions: [],
            preferences: [],
          },
        },
      ],
    });
    api.evidenceCitation = vi
      .fn()
      .mockRejectedValue(new Error("Evidence not found"));
    render(
      <ResearchResultsPanel
        api={api}
        job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
      />,
    );
    fireEvent.click(
      await screen.findByText(/Some required details are unknown/),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "View supporting source" }),
    );
    expect(
      await screen.findByText(/citation may have expired, been removed/),
    ).toBeVisible();
  });
  it("aborts an outstanding citation when the displayed run changes", async () => {
    const api = client();
    const evidenceId = "00000000-0000-4000-8000-000000000003";
    api.results.mockResolvedValue({
      ...result,
      results: [
        {
          ...result.results[0],
          fit: {
            status: "near_match",
            limitations: [],
            preference_score: 0,
            essential: [
              {
                criterion: {
                  field: "location",
                  operator: "contains",
                  value: "Bengaluru",
                },
                outcome: "unknown",
                reason: "Not in retained facts.",
                evidence_ids: [evidenceId],
              },
            ],
            exclusions: [],
            preferences: [],
          },
        },
      ],
    });
    const citationRequest = vi.fn().mockReturnValue(new Promise(() => {}));
    api.evidenceCitation = citationRequest;
    const view = render(
      <ResearchResultsPanel
        api={api}
        job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
      />,
    );
    fireEvent.click(
      await screen.findByText(/Some required details are unknown/),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "View supporting source" }),
    );
    expect(citationRequest).toHaveBeenCalled();
    const signal = citationRequest.mock.calls[0][3] as AbortSignal;
    view.rerender(
      <ResearchResultsPanel
        api={api}
        job={{ id: "j2", status: "accepted", workspace_id: "w1" }}
      />,
    );
    expect(signal.aborted).toBe(true);
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
    expect(
      screen.getByText(
        /Network 1.25s \(1 sample\).*Parser 0.2s \(1 sample\).*Browser timing unavailable \(0 samples\)/,
      ),
    ).toBeVisible();
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

it("shows unverified feed items with distinct dates and safe literal content", async () => {
  const api = client();
  api.results.mockResolvedValue({
    ...result,
    results: result.results.map((item) => ({
      ...item,
      source: "rss",
      feed: {
        feed_url: "https://example.com/feed",
        duplicate_count: 1,
        invalid_link_count: 1,
        omitted_entry_count: 2,
        evidence_expired: false,
        entries: [
          {
            entry_id: "one",
            title: "Updated entry",
            url: "https://example.com/one",
            published_at: null,
            updated_at: "2026-10-13T12:00:00Z",
            summary: "<script>source data</script>",
            summary_truncated: false,
          },
          {
            entry_id: "two",
            title: "Unsafe link",
            url: "javascript:alert(1)",
            published_at: null,
            updated_at: null,
            summary: "",
            summary_truncated: false,
          },
        ],
      },
    })),
  });
  const { container } = render(
    <ResearchResultsPanel api={api} job={{ id: "j1", status: "accepted" }} />,
  );
  const feedSummary = await screen.findByText(/Feed entries \(2\)/);
  fireEvent.click(feedSummary);
  expect(screen.getAllByText(/Publication date not provided/)).toHaveLength(2);
  expect(screen.getByText(/Updated/, { selector: "p" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Updated entry" })).toHaveAttribute(
    "href",
    "https://example.com/one",
  );
  expect(
    screen.queryByRole("link", { name: "Unsafe link" }),
  ).not.toBeInTheDocument();
  expect(container.querySelector("script")).toBeNull();
  expect(screen.getByText("<script>source data</script>")).toBeInTheDocument();
  expect(screen.getByText(/1 repeated entries omitted/)).toBeInTheDocument();
});

it("explains expired feed evidence without showing prior items", async () => {
  const api = client();
  api.results.mockResolvedValue({
    ...result,
    results: result.results.map((item) => ({
      ...item,
      source: "rss",
      feed: {
        feed_url: "https://example.com/feed",
        entries: [],
        duplicate_count: 0,
        invalid_link_count: 0,
        omitted_entry_count: 0,
        evidence_expired: true,
      },
    })),
  });
  render(
    <ResearchResultsPanel api={api} job={{ id: "j1", status: "accepted" }} />,
  );
  expect(await screen.findByText(/Feed evidence expired/)).toBeInTheDocument();
  expect(
    screen.queryByText(/Publication date not provided/),
  ).not.toBeInTheDocument();
});

it("labels public YouTube metadata and renders timestamped, scoped caption evidence", async () => {
  const api = client();
  api.evidenceCitation = vi.fn().mockResolvedValue({
    id: "00000000-0000-0000-0000-000000000002",
    source_url: "https://www.youtube.com/watch?v=BaW_jenozKc",
    source_platform: "youtube",
    excerpt: "Synthetic caption cue",
    excerpt_truncated: false,
    collected_at: "2026-10-14T00:00:00Z",
    expires_at: null,
    content_hash: null,
    content_hash_status: "stored_metadata_not_revalidated",
  });
  api.results.mockResolvedValue({
    ...result,
    results: [
      {
        ...result.results[0],
        source: "youtube",
        youtube: {
          metadata: {
            source: "youtube",
            evidence_kind: "public_video_metadata",
            counter_scope: "public_metadata",
            title: "Public video",
            channel: "Example channel",
            channel_url: "https://www.youtube.com/@example",
            description: null,
            duration_seconds: 125.5,
            view_count: 4200,
            like_count: 12,
            observed_at: "2026-10-14T00:00:00Z",
            published_on: "2026-10-10",
            source_url: "https://www.youtube.com/watch?v=BaW_jenozKc",
            transcript_languages: ["en"],
            transcript_state: "available",
          },
          metadata_truncated: false,
          caption_status: "retrieved",
          caption_origin: "platform_automatic",
          caption_language: "en",
          segments: [
            {
              claim_id: "00000000-0000-0000-0000-000000000001",
              evidence_id: "00000000-0000-0000-0000-000000000002",
              start_seconds: 1.25,
              end_seconds: 3.5,
              text: "Synthetic caption cue",
            },
          ],
          omitted_segments: 0,
          subject_identity: "unknown",
          evidence_expired: false,
        },
      },
    ],
  });
  render(
    <ResearchResultsPanel
      api={api}
      job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
    />,
  );
  const publicViews = await screen.findByText("Public views when observed");
  expect(publicViews.parentElement).toHaveTextContent("4,200");
  expect(screen.getByText(/not private YouTube Analytics/)).toBeVisible();
  expect(screen.getByText(/creator identity is unknown/)).toBeVisible();
  expect(screen.getByText("Platform-generated captions · en")).toBeVisible();
  const timestamp = screen.getByRole("link", { name: "1.3s–3.5s" });
  expect(timestamp).toHaveAttribute(
    "href",
    "https://www.youtube.com/watch?v=BaW_jenozKc&t=1s",
  );
  fireEvent.click(
    screen.getByRole("button", { name: "View supporting source" }),
  );
  expect(
    await screen.findByText(
      "Content hash is stored metadata and has not been revalidated against the source.",
    ),
  ).toBeVisible();
  expect(api.evidenceCitation).toHaveBeenCalledWith(
    "j1",
    "00000000-0000-0000-0000-000000000002",
    "w1",
    expect.any(AbortSignal),
  );
});

it("hides expired YouTube metadata and caption text", async () => {
  const api = client();
  api.results.mockResolvedValue({
    ...result,
    results: [
      {
        ...result.results[0],
        youtube: {
          metadata: null,
          metadata_truncated: false,
          caption_status: "unavailable",
          caption_origin: null,
          caption_language: null,
          segments: [],
          omitted_segments: 0,
          subject_identity: "unknown",
          evidence_expired: true,
        },
      },
    ],
  });
  render(
    <ResearchResultsPanel api={api} job={{ id: "j1", status: "accepted" }} />,
  );
  expect(await screen.findByText("YouTube evidence expired")).toBeVisible();
  expect(screen.queryByText(/Synthetic caption cue/)).not.toBeInTheDocument();
});
