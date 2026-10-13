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
    },
  ],
};
function client() {
  const api = createApi("http://test", vi.fn());
  return {
    ...api,
    job: vi.fn().mockResolvedValue(run),
    results: vi.fn().mockResolvedValue(result),
  };
}
afterEach(() => vi.useRealTimers());
describe("actual research results", () => {
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
    expect(screen.getByText("No qualification performed.")).toBeVisible();
    expect(api.job).toHaveBeenCalledWith("j1", "w1", expect.any(AbortSignal));
    expect(api.results).toHaveBeenCalledTimes(1);
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
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
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
