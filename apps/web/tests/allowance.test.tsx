import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WorkspaceAllowancePanel } from "../src/components/workspace-allowance";
import { createApi } from "../src/lib/api";

const policy = {
  workspace_id: "w1",
  tier: "trial" as const,
  enabled: true,
  can_manage: true,
  run_limit: 25,
  result_cap: 25,
  source_cap: 3,
  result_limit: 25,
  source_limit: 3,
  used_runs: 2,
  remaining_runs: 23,
};
function client(canManage = true) {
  const api = createApi("http://test", vi.fn());
  return {
    ...api,
    allowance: vi.fn().mockResolvedValue({ ...policy, can_manage: canManage }),
    updateAllowance: vi
      .fn()
      .mockImplementation(async (_id, settings) => ({
        ...policy,
        ...settings,
      })),
  };
}
describe("workspace allowance", () => {
  it("saves owner limits and preserves the used run count", async () => {
    const api = client();
    render(<WorkspaceAllowancePanel api={api} />);
    fireEvent.click(
      await screen.findByText("Workspace allowance · 23 runs remaining"),
    );
    fireEvent.change(
      screen.getByRole("spinbutton", { name: "Results per run" }),
      { target: { value: "10" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Save workspace settings" }),
    );
    expect(await screen.findByText("Workspace settings saved.")).toBeVisible();
    expect(api.updateAllowance).toHaveBeenCalledWith("w1", {
      enabled: true,
      result_limit: 10,
      source_limit: 3,
    });
    expect(screen.getByText(/2 of 25 run admissions used/)).toBeVisible();
  });
  it("blocks values beyond the provisioned ceiling before a save", async () => {
    const api = client();
    render(<WorkspaceAllowancePanel api={api} />);
    fireEvent.click(
      await screen.findByText("Workspace allowance · 23 runs remaining"),
    );
    fireEvent.change(
      screen.getByRole("spinbutton", { name: "Sources per run" }),
      { target: { value: "4" } },
    );
    expect(
      screen.getByRole("button", { name: "Save workspace settings" }),
    ).toBeDisabled();
    expect(api.updateAllowance).not.toHaveBeenCalled();
  });
  it("does not offer owner controls to members", async () => {
    const api = client(false);
    render(<WorkspaceAllowancePanel api={api} />);
    fireEvent.click(
      await screen.findByText("Workspace allowance · 23 runs remaining"),
    );
    expect(
      screen.getByText(
        "Only the workspace owner can change execution settings.",
      ),
    ).toBeVisible();
    expect(
      screen.queryByRole("form", { name: "Workspace execution settings" }),
    ).not.toBeInTheDocument();
  });
});
