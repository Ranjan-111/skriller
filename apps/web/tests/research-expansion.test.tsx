import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ResearchExpansion } from "../src/components/research-expansion";
import type { createApi } from "../src/lib/api";

it("starts an expanded research run from an explicit prompt and opens that run", async () => {
  const next = { id: "next", workspace_id: "w1", status: "queued" };
  const api = { expandResearch: vi.fn().mockResolvedValue(next) };
  const onStarted = vi.fn();
  render(
    <ResearchExpansion
      api={api as unknown as ReturnType<typeof createApi>}
      sourceJobId="source"
      workspaceId="w1"
      onStarted={onStarted}
    />,
  );
  fireEvent.click(screen.getByText("Search further from this run"));
  fireEvent.change(
    screen.getByRole("textbox", { name: "Further research prompt" }),
    { target: { value: "Find more companies in India" } },
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Start expanded research" }),
  );
  await screen.findByRole("button", { name: "Start expanded research" });
  expect(api.expandResearch).toHaveBeenCalledWith(
    "source",
    "w1",
    "Find more companies in India",
  );
  expect(onStarted).toHaveBeenCalledWith(next, "Find more companies in India");
});
