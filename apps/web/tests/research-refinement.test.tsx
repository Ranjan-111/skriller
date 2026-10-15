import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import { ResearchRefinement } from "../src/components/research-refinement";
import type { createApi } from "../src/lib/api";

test("explicit refinement starts a new run and keeps the old run visible until confirmation", async () => {
  const next = { id: "new-job", workspace_id: "workspace", status: "queued" };
  const refineResearch = vi.fn().mockResolvedValue(next);
  const onStarted = vi.fn();
  render(
    <ResearchRefinement
      api={{ refineResearch } as unknown as ReturnType<typeof createApi>}
      sourceJobId="old-job"
      workspaceId="workspace"
      onStarted={onStarted}
    />,
  );
  fireEvent.click(screen.getByText("Refine this search"));
  fireEvent.change(screen.getByLabelText("Refinement prompt"), {
    target: { value: "Exclude consultancies" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Refine and run" }));
  await waitFor(() =>
    expect(onStarted).toHaveBeenCalledWith(next, "Exclude consultancies"),
  );
  expect(refineResearch).toHaveBeenCalledWith(
    "old-job",
    "workspace",
    "Exclude consultancies",
  );
});
