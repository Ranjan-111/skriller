import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SavedListsPanel } from "../src/components/saved-lists-panel";
import type { createApi, ResearchCandidate } from "../src/lib/api";

const id = "00000000-0000-4000-8000-000000000001";
const list = {
  id,
  workspace_id: "w1",
  name: "Prospects",
  plan_id: "p1",
  created_by: "owner",
  created_at: "2026-10-14T00:00:00Z",
};
const snapshot = (revision: number) => ({
  id,
  workspace_id: "w1",
  list_id: id,
  revision,
  plan_id: "p1",
  created_at: "2026-10-14T00:00:00Z",
  created_by: "owner",
  payload: {
    snapshot_at: "2026-10-14T00:00:00Z",
    members: [
      {
        entity_id: id,
        display_name: "Acme",
        fit: {
          status: "near_match" as const,
          preference_score: 0,
          limitations: [],
          essential: [],
          exclusions: [],
          preferences: [],
        },
        values: [],
        identity_status: "reviewed_facts" as const,
      },
    ],
    omitted: [],
    refresh_scope: "persisted_reviewed_facts_only" as const,
  },
});
const candidate = {
  id,
  title: "Acme",
  url: "https://example.org",
  snippet: "Public profile",
  source: "web",
  provider: "exa_keyless",
  evidence_kind: "search_snippet",
  qualification: "unverified",
  observed_at: "2026-10-14T00:00:00Z",
  provenance: [],
} as ResearchCandidate;

function client() {
  const api = {
    savedLists: vi.fn().mockResolvedValue([]),
    createSavedList: vi.fn().mockResolvedValue(list),
    savedListSnapshot: vi.fn().mockResolvedValue(snapshot(1)),
    refreshSavedList: vi.fn().mockResolvedValue(snapshot(2)),
  };
  return api as unknown as ReturnType<typeof createApi> & typeof api;
}

describe("saved-list panel", () => {
  it("saves selected result IDs and displays a frozen revision", async () => {
    const api = client();
    render(
      <SavedListsPanel
        api={api}
        workspaceId="w1"
        planId="p1"
        candidates={[candidate]}
      />,
    );
    await screen.findByText("No saved lists in this workspace.");
    fireEvent.click(screen.getByText("Save current results (1 max)"));
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(
      screen.getByRole("button", { name: "Save 1 selected result" }),
    );
    expect(
      await screen.findByText(/Saved as immutable revision 1/),
    ).toBeInTheDocument();
    expect(api.createSavedList).toHaveBeenCalledWith(
      "w1",
      "Research results",
      "p1",
      [id],
    );
    expect(api.savedListSnapshot).toHaveBeenCalledWith("w1", id);
    expect(
      document.querySelector(".saved-list-snapshot strong"),
    ).toHaveTextContent("Revision 1");
    expect(
      screen.getByText(/persisted reviewed facts only/),
    ).toBeInTheDocument();
  });

  it("refreshes with the displayed expected revision and retains list history wording", async () => {
    const api = client();
    api.savedLists.mockResolvedValue([list]);
    render(
      <SavedListsPanel
        api={api}
        workspaceId="w1"
        planId={null}
        candidates={[]}
      />,
    );
    fireEvent.change(
      await screen.findByRole("combobox", { name: "Open saved list" }),
      { target: { value: id } },
    );
    await screen.findByRole("button", {
      name: /Create a new persisted-facts revision/,
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: /Create a new persisted-facts revision/,
      }),
    );
    await screen.findByText(/Created revision 2/);
    expect(api.refreshSavedList).toHaveBeenCalledWith("w1", id, [id], 1);
    expect(
      document.querySelector(".saved-list-snapshot strong"),
    ).toHaveTextContent("Revision 2");
  });

  it("surfaces owner-only authorization errors without losing the saved list", async () => {
    const api = client();
    api.savedLists.mockResolvedValue([list]);
    api.refreshSavedList.mockRejectedValue(
      new Error("Only a workspace owner can refresh lists."),
    );
    render(
      <SavedListsPanel
        api={api}
        workspaceId="w1"
        planId={null}
        candidates={[]}
      />,
    );
    fireEvent.change(
      await screen.findByRole("combobox", { name: "Open saved list" }),
      { target: { value: id } },
    );
    await screen.findByRole("button", {
      name: /Create a new persisted-facts revision/,
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: /Create a new persisted-facts revision/,
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /workspace owner/,
    );
    expect(document.querySelector(".saved-list-snapshot ul > li")).toHaveTextContent("Acme");
  });
});
