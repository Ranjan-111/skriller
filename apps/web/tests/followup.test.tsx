import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { FollowupPanel } from "../src/components/followup-panel";
import type { createApi, ResearchCandidate } from "../src/lib/api";

const candidate = {
  id: "entity",
  title: "Synthetic company",
  url: "https://example.org/company",
  snippet: "Indexed reference",
  source: "web",
  provider: "exa_keyless",
  evidence_kind: "search_snippet",
  qualification: "unverified",
  observed_at: "2026-10-14T00:00:00Z",
  provenance: [],
  fit: {
    status: "confirmed",
    preference_score: 0,
    limitations: [],
    essential: [
      {
        criterion: { field: "employee_count", operator: "gte", value: 10 },
        outcome: "matched",
        reason: "supported_by_accepted_fact",
        evidence_ids: ["evidence"],
      },
    ],
    exclusions: [],
    preferences: [],
  },
} as ResearchCandidate;

it("shows exact cited source statements with an explicit verification limit", async () => {
  const api = {
    submitFollowup: vi
      .fn()
      .mockResolvedValue({
        job_id: "followup",
        workspace_id: "workspace",
        state: "queued",
      }),
    followupReport: vi.fn().mockResolvedValue({
      job_id: "followup",
      source_job_id: "source",
      entity_id: "entity",
      state: "completed",
      status: "answered",
      observations: [
        {
          evidence_id: "evidence",
          quote: "25 employees",
          source_url: "https://example.org/company",
          source_platform: "web",
          collected_at: "2026-10-14T00:00:00Z",
          excerpt_sha256: "a".repeat(64),
          qualification: "source_statement_not_independently_verified",
        },
      ],
      unknowns: [],
      coverage_complete: false,
      inference_status: "unavailable",
      expansion_status: "unavailable",
    }),
  };
  render(
    <FollowupPanel
      api={api as unknown as ReturnType<typeof createApi>}
      sourceJobId="source"
      workspaceId="workspace"
      candidate={candidate}
    />,
  );
  fireEvent.click(screen.getByText("Ask about reviewed evidence"));
  fireEvent.click(screen.getByRole("button", { name: "Ask follow-up" }));
  expect(await screen.findByText("25 employees")).toBeInTheDocument();
  expect(api.submitFollowup).toHaveBeenCalledWith(
    "source",
    "workspace",
    "entity",
    "Why does this result fit?",
  );
  expect(
    screen.getAllByText(/not independently verified/).length,
  ).toBeGreaterThan(0);
  expect(screen.getByRole("link", { name: "Open source" })).toHaveAttribute(
    "href",
    "https://example.org/company",
  );
});

it("keeps unsupported answers explicitly unknown", async () => {
  const api = {
    submitFollowup: vi
      .fn()
      .mockResolvedValue({
        job_id: "followup",
        workspace_id: "workspace",
        state: "queued",
      }),
    followupReport: vi
      .fn()
      .mockResolvedValue({
        job_id: "followup",
        source_job_id: "source",
        entity_id: "entity",
        state: "completed",
        status: "unknown",
        observations: [],
        unknowns: ["evidence_no_longer_accessible"],
        coverage_complete: false,
        inference_status: "unavailable",
        expansion_status: "unavailable",
      }),
  };
  render(
    <FollowupPanel
      api={api as unknown as ReturnType<typeof createApi>}
      sourceJobId="source"
      workspaceId="workspace"
      candidate={candidate}
    />,
  );
  fireEvent.click(screen.getByText("Ask about reviewed evidence"));
  fireEvent.click(screen.getByRole("button", { name: "Ask follow-up" }));
  expect(
    await screen.findByText(/No supported answer is available/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "Open source" }),
  ).not.toBeInTheDocument();
});
