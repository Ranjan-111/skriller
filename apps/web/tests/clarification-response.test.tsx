import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ClarificationResponse } from "../src/components/clarification-response";
import type { createApi } from "../src/lib/api";

test("submits a clarification and advances to the confirmed planning job", async () => {
  const next = {
    id: "planning-job",
    workspace_id: "workspace",
    status: "queued",
  };
  const answerClarification = vi.fn().mockResolvedValue(next);
  const onStarted = vi.fn();
  render(
    <ClarificationResponse
      api={{ answerClarification } as unknown as ReturnType<typeof createApi>}
      jobId="old-job"
      workspaceId="workspace"
      question="Should location refer to the person or company headquarters?"
      onStarted={onStarted}
    />,
  );
  fireEvent.change(screen.getByLabelText("Your answer"), {
    target: { value: "Company headquarters" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Answer and continue" }));
  await waitFor(() => expect(onStarted).toHaveBeenCalledWith(next));
  expect(answerClarification).toHaveBeenCalledWith(
    "old-job",
    "workspace",
    "Company headquarters",
  );
});
