import { StrictMode } from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { YouTubeAnalyticsPanel } from "../src/components/youtube-analytics";
import { createApi } from "../src/lib/api";
import { CONSENT_KEY } from "../src/lib/analytics-consent";
import type {
  AnalyticsGrant,
  AnalyticsReport,
} from "../src/lib/youtube-analytics";

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
const report: AnalyticsReport = {
  status: "partial",
  grant_id: grant.id,
  channel_id: grant.channel_id!,
  start_date: "2020-01-01",
  end_date: "2020-01-05",
  timezone: "America/Los_Angeles",
  currency: null,
  coverage_complete: false,
  availability: "provider_returned_days_only",
  rows: [
    { day: "2020-01-02", metrics: { views: 42, averageViewDuration: 3.5 } },
  ],
  units: { views: "count", averageViewDuration: "seconds" },
  unavailable_metrics: { estimatedMinutesWatched: "unavailable" },
  source_url: "https://youtubeanalytics.googleapis.com/v2/reports",
  source_platform: "youtube_analytics",
  collected_at: "2020-01-06T00:00:00Z",
  response_sha256: "a".repeat(64),
  summary: ["Private channel metric: 42 views."],
  summary_status: "literal_metrics_only",
};
function client(owner = true) {
  return {
    ...createApi("http://test", vi.fn()),
    allowance: vi
      .fn()
      .mockResolvedValue({ workspace_id: workspace, can_manage: owner }),
    analyticsGrants: vi.fn().mockResolvedValue([grant]),
    analyticsComplete: vi.fn().mockResolvedValue(grant),
    analyticsReport: vi.fn().mockResolvedValue(report),
    analyticsSummaryStart: vi.fn().mockResolvedValue({ job_id: "44444444-4444-4444-8444-444444444444", state: "completed", summary_state: "completed", result: { status: "partial", coverage_complete: false, expansion_status: "unavailable", inference_status: "unavailable", inferences: [], observations: [{ evidence_id: "obs-1", quote: "42 views", source_url: "https://youtube.com/channel", source_platform: "youtube_analytics", collected_at: "2020-01-06T00:00:00Z", excerpt_sha256: "a".repeat(64), stored_content_sha256: null, qualification: "source_statement_not_independently_verified", content_hash_status: "stored_metadata_not_revalidated" }], unknowns: ["Revenue was not requested."], supplied_evidence_count: 1, used_evidence_count: 1 } }),
    analyticsSummaryGet: vi.fn(),
    analyticsSummaryCancel: vi.fn(),
    analyticsRefresh: vi.fn().mockResolvedValue(grant),
    analyticsRevoke: vi.fn().mockResolvedValue({ ...grant, state: "revoked" }),
  };
}
afterEach(() => {
  sessionStorage.clear();
  window.history.replaceState(null, "", "/");
});
async function readReport() {
  await screen.findByLabelText("Channel connection");
  fireEvent.change(screen.getByLabelText("From"), {
    target: { value: "2020-01-01" },
  });
  fireEvent.change(screen.getByLabelText("Through"), {
    target: { value: "2020-01-05" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Read daily report" }));
}
describe("YouTube owner analytics", () => {
  it("shows exact metrics and units without fabricating missing days or revenue", async () => {
    const api = client();
    render(
      <YouTubeAnalyticsPanel
        api={api}
        userId="owner"
        identityStatus="signed_in"
      />,
    );
    fireEvent.click(screen.getByText("YouTube owner analytics"));
    await readReport();
    expect(
      await screen.findByText("Private channel metric: 42 views."),
    ).toBeVisible();
    expect(screen.getByRole("cell", { name: "3.5" })).toBeVisible();
    expect(screen.getByText(/Missing days are unknown/)).toBeVisible();
    expect(
      screen.getByRole("columnheader", {
        name: "Average view duration (seconds)",
      }),
    ).toBeVisible();
    expect(
      screen.queryByRole("rowheader", { name: "2020-01-03" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Disconnect channel" }));
    await waitFor(() =>
      expect(api.analyticsRevoke).toHaveBeenCalledWith(workspace, grant.id),
    );
    expect(
      screen.queryByText("Private channel metric: 42 views."),
    ).not.toBeInTheDocument();
  });
  it("keeps model summary private and renders only quoted observations with source links", async () => {
    const api = client();
    render(<YouTubeAnalyticsPanel api={api} userId="owner" identityStatus="signed_in" />);
    fireEvent.click(screen.getByText("YouTube owner analytics"));
    await readReport();
    fireEvent.click(await screen.findByRole("button", { name: "Generate private model summary" }));
    expect(await screen.findByText("42 views")).toBeVisible();
    await waitFor(() => expect(screen.getByRole("button", { name: "Generate private model summary" })).toBeEnabled());
    expect(screen.getByRole("link", { name: "youtube_analytics source" })).toHaveAttribute("href", "https://youtube.com/channel");
    expect(api.analyticsSummaryStart).toHaveBeenCalledWith(workspace, grant, { start_date: "2020-01-01", end_date: "2020-01-05", metrics: ["views", "estimatedMinutesWatched", "averageViewDuration"] }, expect.stringMatching(/^[0-9a-f-]{36}$/i));
    expect(screen.getByText("Unknown: Revenue was not requested.")).toBeVisible();
  });
  it("waits for identity, clears callback URL, and completes consent once in StrictMode", async () => {
    const api = client(),
      state = "a".repeat(43);
    sessionStorage.setItem(
      CONSENT_KEY,
      JSON.stringify({
        uid: "owner",
        workspace,
        grant: grant.id,
        state,
        expires: Date.now() + 100000,
      }),
    );
    window.history.replaceState(null, "", `/?code=private-code&state=${state}`);
    const view = render(
      <StrictMode>
        <YouTubeAnalyticsPanel api={api} identityStatus="loading" />
      </StrictMode>,
    );
    expect(window.location.search).toBe("");
    expect(api.analyticsComplete).not.toHaveBeenCalled();
    view.rerender(
      <StrictMode>
        <YouTubeAnalyticsPanel
          api={api}
          userId="owner"
          identityStatus="signed_in"
        />
      </StrictMode>,
    );
    await waitFor(() =>
      expect(api.analyticsComplete).toHaveBeenCalledExactlyOnceWith(
        workspace,
        grant.id,
        state,
        "private-code",
      ),
    );
    expect(sessionStorage.getItem(CONSENT_KEY)).toBeNull();
  });
  it("hides previous private report immediately when accounts change", async () => {
    const api = client();
    const view = render(
      <YouTubeAnalyticsPanel
        api={api}
        userId="owner"
        identityStatus="signed_in"
      />,
    );
    fireEvent.click(screen.getByText("YouTube owner analytics"));
    await readReport();
    await screen.findByText("Private channel metric: 42 views.");
    view.rerender(
      <YouTubeAnalyticsPanel
        api={api}
        userId="other"
        identityStatus="signed_in"
      />,
    );
    expect(
      screen.queryByText("Private channel metric: 42 views."),
    ).not.toBeInTheDocument();
    await act(async () => {});
  });
  it("does not load private grants for a workspace member", async () => {
    const api = client(false);
    render(
      <YouTubeAnalyticsPanel
        api={api}
        userId="member"
        identityStatus="signed_in"
      />,
    );
    fireEvent.click(screen.getByText("YouTube owner analytics"));
    expect(await screen.findByText(/Only the workspace owner/)).toBeVisible();
    expect(api.analyticsGrants).not.toHaveBeenCalled();
  });
  it("starts explicit consent with a tab-local owner/workspace/state binding", async () => {
    const state = "a".repeat(43),
      navigate = vi.fn();
    const url = new URL("https://accounts.google.com/o/oauth2/v2/auth");
    url.searchParams.set("state", state);
    url.searchParams.set("redirect_uri", window.location.origin + "/");
    const api = {
      ...client(),
      analyticsStart: vi
        .fn()
        .mockResolvedValue({
          grant_id: grant.id,
          authorization_url: url.href,
          expires_at: new Date(Date.now() + 100000).toISOString(),
        }),
    };
    render(
      <YouTubeAnalyticsPanel
        api={api}
        userId="owner"
        identityStatus="signed_in"
        navigate={navigate}
      />,
    );
    fireEvent.click(screen.getByText("YouTube owner analytics"));
    await screen.findByLabelText("Channel connection");
    fireEvent.click(
      screen.getByRole("button", { name: "Connect owned channel" }),
    );
    await waitFor(() => expect(navigate).toHaveBeenCalledWith(url.href));
    expect(JSON.parse(sessionStorage.getItem(CONSENT_KEY)!)).toMatchObject({
      uid: "owner",
      workspace,
      grant: grant.id,
      state,
    });
    expect(sessionStorage.getItem(CONSENT_KEY)).not.toContain("private-code");
  });
  it("blocks oversized date ranges without a report request", async () => {
    const api = client();
    render(
      <YouTubeAnalyticsPanel
        api={api}
        userId="owner"
        identityStatus="signed_in"
      />,
    );
    fireEvent.click(screen.getByText("YouTube owner analytics"));
    await screen.findByLabelText("Channel connection");
    fireEvent.change(screen.getByLabelText("From"), {
      target: { value: "2020-01-01" },
    });
    fireEvent.change(screen.getByLabelText("Through"), {
      target: { value: "2020-02-15" },
    });
    expect(
      screen.getByRole("button", { name: "Read daily report" }),
    ).toBeDisabled();
    expect(api.analyticsReport).not.toHaveBeenCalled();
  });
});
