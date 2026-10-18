import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  OwnerRoleReview,
  ResearchResultsPanel,
} from "../src/components/research-results";
import * as exports from "../src/lib/exports";
import { ApiError, createApi, type ResearchCandidate } from "../src/lib/api";

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
  resume_status: "available" as const,
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
    connections: vi.fn().mockResolvedValue([
      {
        id: "00000000-0000-4000-8000-000000000003",
        workspace_id: "w1",
        source: "linkedin",
        auth_kind: "session",
        scopes: ["read", "discover"],
        state: "active",
        expires_at: "2099-01-01T00:00:00Z",
        access_validation: "not_performed",
        remote_revocation: "not_performed",
      },
    ]),
    rebindOptions: vi.fn().mockResolvedValue({
      job_id: "j1",
      job_version: 2,
      confirmation_required: true,
      resume_status: "available",
      options: [
        {
          source: "linkedin",
          entity_ids: ["00000000-0000-4000-8000-000000000001"],
          previous_connection_ref: "00000000-0000-4000-8000-000000000002",
        },
      ],
    }),
    rebindAndResume: vi.fn().mockResolvedValue({ ...run, state: "queued" }),
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

it("refreshes Reddit connection metadata once when progress reports renewal", async () => {
  const api = client();
  api.job.mockResolvedValue({ ...run, state: "running" });
  api.progressEvents = vi.fn(async function* () {
    yield {
      id: "1",
      data: { kind: "source_access_renewed", details: { source: "reddit" } },
    };
  }) as typeof api.progressEvents;
  const onRedditRefresh = vi.fn();
  const view = render(
    <ResearchResultsPanel
      api={api}
      job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
      onRedditRefresh={onRedditRefresh}
    />,
  );
  await vi.waitFor(() => expect(onRedditRefresh).toHaveBeenCalledTimes(1));
  view.unmount();
});

it("refreshes Reddit connection metadata when a run terminates without a renewal event", async () => {
  const api = client();
  api.progressEvents = vi.fn(
    async function* () {},
  ) as typeof api.progressEvents;
  const onRedditRefresh = vi.fn();
  const view = render(
    <ResearchResultsPanel
      api={api}
      job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
      onRedditRefresh={onRedditRefresh}
    />,
  );
  await vi.waitFor(() => expect(onRedditRefresh).toHaveBeenCalledTimes(1));
  view.unmount();
});
afterEach(() => vi.useRealTimers());
describe("actual research results", () => {
  it.each([
    [
      "invalid_interpretation",
      "This request could not be interpreted safely.",
      "Review the prompt and make the people, companies, or evidence you want more specific.",
    ],
    [
      "model_unavailable",
      "The planning service is unavailable.",
      "Check that the configured planning service is ready before starting another run.",
    ],
    [
      "budget_exhausted",
      "This run reached its planning limit.",
      "Review the workspace limits before deciding whether to start another run.",
    ],
    [
      "execution_interrupted",
      "This run stopped before planning could finish.",
      "Review this run before deciding whether to start another one.",
    ],
  ] as const)(
    "explains %s planning failures without retrying and offers prompt editing",
    async (reason, title, nextStep) => {
      const api = client();
      api.submit = vi.fn();
      api.job.mockReturnValue(new Promise(() => {}));
      api.plan.mockResolvedValue({
        job_id: "j1",
        plan_id: "p1",
        workspace_id: "w1",
        status: "rejected",
        planning_failure: {
          reason,
          recovery: {
            invalid_interpretation: "revise_prompt",
            model_unavailable: "check_service",
            budget_exhausted: "check_limits",
            execution_interrupted: "review_run",
          }[reason],
          automatic_retry_allowed: false,
          source_search_started: false,
        },
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
      });
      const onEditPrompt = vi.fn();
      render(
        <ResearchResultsPanel
          api={api}
          job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
          onEditPrompt={onEditPrompt}
        />,
      );
      const recovery = await screen.findByRole("alert");
      expect(within(recovery).getByText(title)).toBeVisible();
      expect(within(recovery).getByText(nextStep)).toBeVisible();
      expect(
        within(recovery).getByText(/Source search did not begin/),
      ).toBeVisible();
      expect(screen.queryByText("location contains Bengaluru")).toBeNull();
      expect(
        screen.queryByText(
          "Sources: web. These are search criteria, not verified facts.",
        ),
      ).toBeNull();
      fireEvent.click(
        within(recovery).getByRole("button", { name: "Edit original prompt" }),
      );
      expect(onEditPrompt).toHaveBeenCalledOnce();
      expect(api.plan).toHaveBeenCalledOnce();
      expect(api.submit).not.toHaveBeenCalled();
      expect(api.job).toHaveBeenCalledOnce();
    },
  );

  it("explains rejected legacy plan responses without claiming a cause", async () => {
    const api = client();
    api.submit = vi.fn();
    api.job.mockReturnValue(new Promise(() => {}));
    api.plan.mockResolvedValue({
      job_id: "j1",
      plan_id: "p1",
      workspace_id: "w1",
      status: "rejected",
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
    });
    render(
      <ResearchResultsPanel
        api={api}
        job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
      />,
    );
    expect(
      await screen.findByText(
        "This run did not produce a validated interpretation.",
      ),
    ).toBeVisible();
    expect(screen.queryByText(/Source search did not begin/)).toBeNull();
    expect(screen.queryByText("location contains Bengaluru")).toBeNull();
    expect(api.submit).not.toHaveBeenCalled();
  });

  it("reloads the plan when asynchronous planning pauses and preserves saved results", async () => {
    const api = client();
    const savedPlan = await api.plan.getMockImplementation()!();
    let resolveRun!: (value: typeof run) => void;
    api.job.mockReturnValue(
      new Promise((resolve) => {
        resolveRun = resolve;
      }),
    );
    api.submit = vi.fn();
    api.plan
      .mockResolvedValueOnce({ ...savedPlan, status: "planning" })
      .mockResolvedValue({
        ...savedPlan,
        status: "rejected",
        planning_failure: {
          reason: "invalid_interpretation",
          recovery: "revise_prompt",
          automatic_retry_allowed: false,
          source_search_started: false,
        },
      });
    render(
      <ResearchResultsPanel
        api={api}
        job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
      />,
    );
    expect(
      await screen.findByText("Interpretation status: planning"),
    ).toBeVisible();
    await act(async () => resolveRun({ ...run, state: "paused" }));
    expect(
      await screen.findByText("This request could not be interpreted safely."),
    ).toBeVisible();
    expect(
      await screen.findByRole("link", { name: /Acme source/ }),
    ).toBeVisible();
    expect(api.plan).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("location contains Bengaluru")).toBeNull();
    expect(api.submit).not.toHaveBeenCalled();
  });

  it.each([
    "success",
    "network",
    "conflict",
    "forbidden",
    "scope-change",
  ] as const)(
    "keeps owner review explicit and handles %s safely",
    async (outcome) => {
      const api = {
        ...createApi("http://test", vi.fn()),
        previewRoleReview: vi.fn().mockResolvedValue({
          entity_id: "entity-1",
          requires_person_confirmation: true,
          previous: {
            role: "Engineer",
            effective_date: "2021-01-01",
            excerpt: "Engineer since 2021",
            source_url: "https://www.linkedin.com/in/sample/",
            role_claim_id: "role-1",
            date_claim_id: "date-1",
            evidence_id: "ev-1",
          },
          replacement: {
            role: "Founder",
            effective_date: "2025-01-01",
            excerpt: "Founder since 2025",
            source_url: "https://www.linkedin.com/in/sample/",
            role_claim_id: "role-2",
            date_claim_id: "date-2",
            evidence_id: "ev-1",
          },
          requires_same_subject_confirmation: true,
          review_hash: "a".repeat(64),
          review_origin: "workspace_owner",
          subject_name: "Synthetic profile",
        }),
        approveRoleReview: vi.fn().mockResolvedValue({}),
      };
      const candidate = {
        id: "entity-1",
        title: "Synthetic profile",
        url: "https://www.linkedin.com/in/sample/",
        snippet: "",
        source: "linkedin",
        provider: "linkedin_mcp",
        evidence_kind: "search_reference",
        qualification: "unverified",
        observed_at: "2026-10-12T00:00:00Z",
        provenance: [],
        linkedin_read: {
          evidence_id: "ev-1",
          resource: { resource_kind: "profile" },
        },
        extraction: {
          observations: [
            {
              claim_id: "role-1",
              field: "job_title",
              value: "Engineer",
              quote: "Engineer since 2021",
              evidence_ids: ["ev-1"],
              status: "unverified",
            },
            {
              claim_id: "date-1",
              field: "role_effective_date",
              value: "2021-01-01",
              quote: "Since 2021",
              evidence_ids: ["ev-1"],
              status: "unverified",
            },
            {
              claim_id: "role-2",
              field: "job_title",
              value: "Founder",
              quote: "Founder since 2025",
              evidence_ids: ["ev-1"],
              status: "unverified",
            },
            {
              claim_id: "date-2",
              field: "role_effective_date",
              value: "2025-01-01",
              quote: "Since 2025",
              evidence_ids: ["ev-1"],
              status: "unverified",
            },
          ],
        },
      } as unknown as ResearchCandidate;
      if (outcome === "network")
        api.approveRoleReview.mockRejectedValue(
          new Error("Cannot reach the research service."),
        );
      if (outcome === "conflict")
        api.approveRoleReview.mockRejectedValue(
          new ApiError("Evidence changed", 409),
        );
      if (outcome === "forbidden")
        api.approveRoleReview.mockRejectedValue(
          new ApiError("Only a workspace owner", 403),
        );
      let resolvePreview: ((value: unknown) => void) | undefined;
      const oldPreview =
        await api.previewRoleReview.getMockImplementation()?.();
      api.previewRoleReview.mockClear();
      if (outcome === "scope-change")
        api.previewRoleReview.mockImplementationOnce(
          () =>
            new Promise((resolve) => {
              resolvePreview = resolve;
            }),
        );
      const onRefresh = vi.fn().mockResolvedValue(undefined);
      const view = render(
        <OwnerRoleReview
          api={api}
          workspaceId="workspace-1"
          candidate={candidate}
          onRefresh={onRefresh}
        />,
      );
      fireEvent.click(
        screen.getByText("Review saved LinkedIn role chronology"),
      );
      expect(api.previewRoleReview).not.toHaveBeenCalled();
      fireEvent.change(screen.getByLabelText("Later role and date"), {
        target: { value: "3" },
      });
      expect(
        screen.getByRole("button", { name: "Preview role change" }),
      ).toBeDisabled();
      expect(api.previewRoleReview).not.toHaveBeenCalled();
      fireEvent.change(screen.getByLabelText("Earlier role and date"), {
        target: { value: "0" },
      });
      fireEvent.click(
        screen.getByRole("button", { name: "Preview role change" }),
      );
      if (outcome === "scope-change") {
        expect(screen.getByLabelText("Earlier role and date")).toBeDisabled();
        view.rerender(
          <OwnerRoleReview
            api={api}
            workspaceId="workspace-2"
            candidate={{ ...candidate, id: "another-entity" }}
            onRefresh={onRefresh}
          />,
        );
        await act(async () => {
          resolvePreview?.(oldPreview);
        });
        expect(
          screen.queryByRole("region", { name: "Role review preview" }),
        ).not.toBeInTheDocument();
        expect(api.approveRoleReview).not.toHaveBeenCalled();
        return;
      }
      const previewSection = await screen.findByRole("region", {
        name: "Role review preview",
      });
      expect(
        within(previewSection).getByText(/Engineer since 2021/),
      ).toBeVisible();
      const confirm = screen.getByRole("button", {
        name: "Confirm role chronology",
      });
      expect(confirm).toBeDisabled();
      fireEvent.click(
        screen.getByLabelText(/confirm both roles describe the same subject/i),
      );
      expect(confirm).toBeDisabled();
      fireEvent.click(
        screen.getByLabelText(
          /separately confirm the original linkedin profile represents a person/i,
        ),
      );
      expect(confirm).toBeEnabled();
      fireEvent.click(confirm);
      if (outcome === "success") await screen.findByRole("status");
      else {
        await screen.findByRole("alert");
        expect(
          screen.queryByRole("region", { name: "Role review preview" }),
        ).not.toBeInTheDocument();
        await vi.waitFor(() =>
          expect(onRefresh).toHaveBeenCalledTimes(
            outcome === "forbidden" ? 0 : 1,
          ),
        );
        expect(api.approveRoleReview).toHaveBeenCalledTimes(1);
        expect(
          screen.getByText("Review saved LinkedIn role chronology"),
        ).toBeVisible();
      }
      expect(api.approveRoleReview).toHaveBeenCalledWith(
        "workspace-1",
        expect.objectContaining({
          same_subject_confirmed: true,
          person_subject_confirmed: true,
        }),
        expect.any(AbortSignal),
      );
    },
  );
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
  it("labels connected LinkedIn results as search references without implying a read", async () => {
    const api = client();
    api.results.mockResolvedValue({
      ...result,
      results: [
        {
          ...result.results[0],
          source: "linkedin",
          provider: "linkedin_mcp",
          evidence_kind: "search_reference",
          platform_reference: {
            source: "linkedin",
            resource_kind: "profile",
            discovery_backend: "linkedin_mcp",
            access: "connected_search_reference_only",
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
    expect(await screen.findByText(/Connected search reference/)).toBeVisible();
    expect(
      screen.getByRole("heading", {
        name: "LinkedIn connected search reference",
      }),
    ).toBeVisible();
    expect(screen.getByText(/no profile or post was opened/)).toBeVisible();
  });
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
  it("renders indexed references as unverified sources with safe original links", async () => {
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
    expect(
      screen.getByText("web · Indexed search reference · Unverified"),
    ).toBeVisible();
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
  it("labels native public posts separately and keeps qualification unverified", async () => {
    const api = client();
    api.results.mockResolvedValue({
      ...result,
      results: [
        result.results[0],
        {
          ...result.results[0],
          id: "native-r1",
          title: "Public discussion",
          url: "https://www.reddit.com/r/example/comments/abc/",
          snippet: "A public post excerpt",
          source: "reddit",
          provider: "reddit_oauth",
          evidence_kind: "public_post",
          provenance: [],
          platform_reference: null,
          discussion: null,
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
      await screen.findByText("reddit · Public post excerpt · Unverified"),
    ).toBeVisible();
    expect(
      screen.getByText("web · Indexed search reference · Unverified"),
    ).toBeVisible();
    expect(
      screen.getByText(/Source excerpts and indexed references are unverified/),
    ).toBeVisible();
    expect(
      screen.getByRole("link", { name: /Public discussion/ }),
    ).toHaveAttribute("href", "https://www.reddit.com/r/example/comments/abc/");
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
  it("requires explicit source, replacement and confirmation before rebinding a checkpoint", async () => {
    const api = client();
    api.job.mockResolvedValue({ ...run, state: "paused", result_count: 1 });
    render(
      <ResearchResultsPanel
        api={api}
        job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
      />,
    );
    fireEvent.click(
      await screen.findByText("Replace source access for pending reads"),
    );
    expect(api.rebindOptions).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Review connection choices" }),
    );
    await screen.findByRole("combobox", { name: "Source to resume" });
    expect(api.rebindOptions).toHaveBeenCalledWith("j1", "w1");
    const submit = screen.getByRole("button", {
      name: "Replace access and resume",
    });
    expect(submit).toBeDisabled();
    fireEvent.change(
      screen.getByRole("combobox", { name: "Source to resume" }),
      {
        target: { value: "linkedin" },
      },
    );
    fireEvent.change(
      screen.getByRole("combobox", { name: "Active replacement connection" }),
      {
        target: { value: "00000000-0000-4000-8000-000000000003" },
      },
    );
    expect(submit).toBeDisabled();
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: /I understand this replaces access/,
      }),
    );
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    await vi.waitFor(() => expect(api.rebindAndResume).toHaveBeenCalledOnce());
    expect(api.rebindAndResume.mock.calls[0][0]).toBe("j1");
    expect(api.rebindAndResume.mock.calls[0][1]).toBe("w1");
    expect(api.rebindAndResume.mock.calls[0][2]).toMatchObject({
      source: "linkedin",
      entity_ids: ["00000000-0000-4000-8000-000000000001"],
      expected_job_version: 2,
      previous_connection_ref: "00000000-0000-4000-8000-000000000002",
      replacement_connection_ref: "00000000-0000-4000-8000-000000000003",
    });
    expect(api.rebindAndResume.mock.calls[0][3]).toMatch(/[0-9a-f-]{36}/i);
  });
  it("reuses the exact idempotent rebind request after an ambiguous failure", async () => {
    const api = client();
    api.job.mockResolvedValue({ ...run, state: "paused" });
    api.rebindAndResume
      .mockRejectedValueOnce(new Error("network interrupted"))
      .mockResolvedValueOnce({ ...run, state: "queued" });
    render(
      <ResearchResultsPanel
        api={api}
        job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
      />,
    );
    fireEvent.click(
      await screen.findByText("Replace source access for pending reads"),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Review connection choices" }),
    );
    fireEvent.change(
      await screen.findByRole("combobox", { name: "Source to resume" }),
      {
        target: { value: "linkedin" },
      },
    );
    fireEvent.change(
      screen.getByRole("combobox", { name: "Active replacement connection" }),
      {
        target: { value: "00000000-0000-4000-8000-000000000003" },
      },
    );
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: /I understand this replaces access/,
      }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Replace access and resume" }),
    );
    expect(await screen.findByText(/network interrupted/)).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: "Retry same confirmed request" }),
    );
    await vi.waitFor(() =>
      expect(api.rebindAndResume).toHaveBeenCalledTimes(2),
    );
    expect(api.rebindAndResume.mock.calls[1]).toEqual(
      api.rebindAndResume.mock.calls[0],
    );
  });
  it("requires fresh owner choices and renewed confirmation after a stale checkpoint", async () => {
    const api = client();
    api.job.mockResolvedValue({ ...run, state: "paused" });
    api.rebindAndResume.mockRejectedValueOnce(
      Object.assign(new Error("checkpoint changed"), { status: 409 }),
    );
    render(
      <ResearchResultsPanel
        api={api}
        job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
      />,
    );
    fireEvent.click(
      await screen.findByText("Replace source access for pending reads"),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Review connection choices" }),
    );
    fireEvent.change(
      await screen.findByRole("combobox", { name: "Source to resume" }),
      { target: { value: "linkedin" } },
    );
    fireEvent.change(
      screen.getByRole("combobox", { name: "Active replacement connection" }),
      { target: { value: "00000000-0000-4000-8000-000000000003" } },
    );
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: /I understand this replaces access/,
      }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Replace access and resume" }),
    );
    expect(await screen.findByText(/checkpoint changed/)).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Review connection choices" }),
    ).toBeEnabled();
    fireEvent.click(
      screen.getByRole("button", { name: "Review connection choices" }),
    );
    await screen.findByRole("combobox", { name: "Source to resume" });
    expect(
      screen.getByRole("button", { name: "Replace access and resume" }),
    ).toBeDisabled();
    expect(api.rebindOptions).toHaveBeenCalledTimes(2);
  });
  it("keeps saved sources visible and offers a retry after the resume preflight changes", async () => {
    const api = client();
    api.job.mockResolvedValueOnce({ ...run, state: "paused" });
    api.resume = vi.fn().mockRejectedValue(new Error("cannot safely resume"));
    render(
      <ResearchResultsPanel
        api={api}
        job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Resume research" }),
    );
    expect(await screen.findByText("cannot safely resume")).toBeVisible();
    expect(
      await screen.findByRole("link", { name: /Acme source/ }),
    ).toBeVisible();
    expect(
      screen.getAllByRole("button", { name: /Check run again/ }).length,
    ).toBeGreaterThan(0);
  });
  it.each([
    ["requires_reconciliation", /needs review before it can resume/],
    ["deadline_expired", /time limit for this run has passed/],
    ["budget_exhausted", /reached its budget/],
    ["new_prompt_required", /needs a corrected prompt/],
    [undefined, /availability cannot be confirmed yet/],
  ] as const)(
    "keeps paused results visible without offering resume when readiness is %s",
    async (resumeStatus, message) => {
      const api = client();
      api.resume = vi.fn();
      api.job.mockResolvedValueOnce({ ...run, state: "paused" });
      api.results.mockResolvedValueOnce({
        ...result,
        ...(resumeStatus
          ? { resume_status: resumeStatus }
          : { resume_status: undefined }),
      });
      render(
        <ResearchResultsPanel
          api={api}
          job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
        />,
      );
      expect(await screen.findByText(message)).toBeVisible();
      expect(
        screen.queryByRole("button", { name: "Resume research" }),
      ).toBeNull();
      expect(
        screen.getByRole("button", { name: /Check run again/ }),
      ).toBeVisible();
      expect(
        await screen.findByRole("link", { name: /Acme source/ }),
      ).toBeVisible();
      expect(api.resume).not.toHaveBeenCalled();
    },
  );
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

it("renders retained Reddit thread context and partial-coverage limits", async () => {
  const api = client();
  const postUrl =
    "https://www.reddit.com/r/synthetic/comments/postabc/thread-title/";
  const commentUrl = `${postUrl}comment/`;
  api.results.mockResolvedValue({
    ...result,
    results: [
      {
        ...result.results[0],
        source: "reddit",
        provider: "reddit_oauth",
        evidence_kind: "public_post",
        url: postUrl,
        reddit_thread: {
          evidence_id: "00000000-0000-4000-8000-000000000062",
          rejected_signals: 1,
          signal_coverage_complete: false,
          signal_failure_code: null,
          signals: [
            {
              resource_id: "t1_comment",
              quote: "We still coordinate this manually.",
              source_url: commentUrl,
              published_at: "2026-10-14T00:00:00Z",
              status: "source_specific_unverified",
              buying_intent: "not_inferred",
            },
          ],
          thread: {
            source: "reddit",
            evidence_kind: "post_comment_read",
            observed_at: "2026-10-14T01:00:00Z",
            coverage_complete: false,
            omitted_comments: 2,
            unexpanded_nodes: 1,
            buying_intent: "not_inferred",
            subject_identity: "unknown",
            post: {
              native_id: "t3_postabc",
              source_url: postUrl,
              title: "Synthetic workflow question",
              subreddit: "synthetic",
              author_handle: null,
              author_identity: "unknown",
              excerpt: "How do you handle operations?",
              content_unavailable: false,
              truncated: false,
              published_at: "2026-10-13T00:00:00Z",
            },
            comments: [
              {
                native_id: "t1_comment",
                parent_id: "t3_postabc",
                source_url: commentUrl,
                text: "We still coordinate this manually.",
                author_handle: null,
                author_identity: "unknown",
                published_at: "2026-10-14T00:00:00Z",
                content_unavailable: false,
                truncated: false,
              },
              {
                native_id: "t1_deleted",
                parent_id: "t1_comment",
                source_url: `${postUrl}deleted/`,
                text: "",
                author_handle: null,
                author_identity: "unknown",
                published_at: null,
                content_unavailable: true,
                truncated: false,
              },
            ],
          },
        },
      },
    ],
  });
  render(
    <ResearchResultsPanel api={api} job={{ id: "j1", status: "accepted" }} />,
  );
  fireEvent.click(
    await screen.findByText("Reddit post and comments (2 retained)"),
  );
  expect(screen.getByText("How do you handle operations?")).toBeVisible();
  expect(screen.getAllByText("We still coordinate this manually.").length).toBe(
    2,
  );
  expect(
    screen.getByText("Comment text unavailable (deleted or removed)."),
  ).toBeVisible();
  expect(
    screen.getByText(/2 comments omitted · 1 reply groups unexpanded/),
  ).toBeVisible();
  expect(screen.getByText(/source-specific and unverified/)).toBeVisible();
  expect(screen.getByText(/1 unsupported quote omitted/)).toBeVisible();
  expect(
    screen.getByText(/does not establish a person, company, buyer/),
  ).toBeVisible();
});

it("downloads displayed research sources through both explicit export actions", async () => {
  const download = vi
    .spyOn(exports, "downloadSources")
    .mockImplementation(() => {});
  const api = client();
  render(
    <ResearchResultsPanel api={api} job={{ id: "j1", status: "accepted" }} />,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Download sources as JSON" }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Download sources as CSV" }),
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

it("shows LinkedIn resource text with its partial coverage limits", async () => {
  const api = client();
  api.results.mockResolvedValue({
    ...result,
    results: [
      {
        ...result.results[0],
        source: "linkedin",
        provider: "linkedin_mcp",
        evidence_kind: "search_reference",
        url: "https://www.linkedin.com/company/synthetic-company/",
        linkedin_read: {
          evidence_id: "00000000-0000-4000-8000-000000000063",
          resource: {
            source: "linkedin",
            evidence_kind: "resource_section_read",
            resource_kind: "company",
            source_url:
              "https://www.linkedin.com/company/synthetic-company/about/",
            section: "about",
            text: "Synthetic company overview text.",
            text_truncated: true,
            observed_at: "2026-10-14T01:00:00Z",
            coverage_complete: false,
            subject_identity: "unknown",
            contact_details: "unavailable",
            buying_intent: "not_inferred",
          },
        },
      },
    ],
  });
  render(
    <ResearchResultsPanel api={api} job={{ id: "j1", status: "accepted" }} />,
  );
  fireEvent.click(await screen.findByText("LinkedIn company overview read"));
  expect(screen.getByText(/Synthetic company overview text/)).toBeVisible();
  expect(screen.getByText(/Coverage is partial/)).toBeVisible();
  expect(screen.getByText(/section text shortened/)).toBeVisible();
  expect(
    screen.getByRole("link", { name: /Open the LinkedIn source/ }),
  ).toHaveAttribute(
    "href",
    "https://www.linkedin.com/company/synthetic-company/about/",
  );
});

it("explains when retained LinkedIn read text has expired", async () => {
  const api = client();
  api.results.mockResolvedValue({
    ...result,
    results: [
      {
        ...result.results[0],
        source: "linkedin",
        provider: "linkedin_mcp",
        evidence_kind: "search_reference",
        collection: { status: "read", failure_code: null },
      },
    ],
  });
  render(
    <ResearchResultsPanel api={api} job={{ id: "j1", status: "accepted" }} />,
  );
  expect(
    await screen.findByText(
      /LinkedIn was read, but the retained section text has expired/,
    ),
  ).toBeVisible();
});

it.each(["instagram", "facebook"] as const)(
  "renders bounded %s observations without inferring identity or missing counts",
  async (source) => {
    const { socialCandidate } = await import("./social-fixtures");
    const api = client();
    api.submit = vi.fn();
    api.results.mockResolvedValue({
      ...result,
      results: [socialCandidate(source)],
    });
    const view = render(
      <ResearchResultsPanel
        api={api}
        job={{ id: "j1", status: "accepted", workspace_id: "w1" }}
      />,
    );
    await screen.findByText(
      source === "instagram"
        ? "Instagram public profile read"
        : "Facebook profile header read",
    );
    if (source === "instagram") {
      expect(screen.getByText(/Followers: Unknown/)).toHaveTextContent(
        "Following: 0",
      );
      expect(
        screen.getByText(/Owner analytics are unavailable/),
      ).toBeInTheDocument();
    } else {
      expect(screen.getByText(/1.2K followers/)).toHaveTextContent(
        "Friends shown: Unknown",
      );
      expect(
        screen.getByText(/Group access is unavailable/),
      ).toBeInTheDocument();
    }
    expect(api.submit).not.toHaveBeenCalled();
    view.unmount();
  },
);
