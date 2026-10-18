import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { QualifiedExportPanel } from "../src/components/qualified-export-panel";
import { createApi, type ResearchCandidate } from "../src/lib/api";
import { createQualifiedExportClient } from "../src/lib/qualified-exports";
import * as files from "../src/lib/qualified-exports";
const workspace = "00000000-0000-4000-8000-000000000001";
const plan = "00000000-0000-4000-8000-000000000002";
const entity = "00000000-0000-4000-8000-000000000003";
const metadata = {
  id: "00000000-0000-4000-8000-000000000004",
  format: "csv",
  row_count: 1,
  expires_at: "2099-01-01T00:00:00Z",
  schema_version: "skriller-qualified-v1",
};
const confirmed = {
  id: entity,
  fit: { status: "confirmed" },
} as ResearchCandidate;
afterEach(() => vi.restoreAllMocks());
it("creates and downloads private exports with bearer authentication and no URL tokens", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(metadata)))
    .mockResolvedValueOnce(
      new Response("name\r\nSynthetic", {
        headers: { "Content-Type": "text/csv; charset=utf-8" },
      }),
    );
  const api = createApi(
    "https://api.example",
    fetcher,
    async () => "fixture-token",
  );
  await api.qualifiedExport(workspace, plan, [entity], "csv");
  const blob = await api.qualifiedExportDownload(workspace, metadata.id, "csv");
  expect(await blob.text()).toContain("Synthetic");
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({
    plan_id: plan,
    entity_ids: [entity],
    format: "csv",
  });
  for (const [url, init] of fetcher.mock.calls) {
    expect(url).not.toContain("fixture-token");
    expect(init.headers.get("Authorization")).toBe("Bearer fixture-token");
    expect(init.cache).toBe("no-store");
  }
});
it("rejects misleading metadata and non-file responses", async () => {
  const request = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ ...metadata, row_count: 2 })),
    )
    .mockResolvedValueOnce(
      new Response("<html>login</html>", {
        headers: { "Content-Type": "text/html" },
      }),
    );
  const api = createQualifiedExportClient(request);
  await expect(
    api.qualifiedExport(workspace, plan, [entity], "csv"),
  ).rejects.toThrow("invalid export confirmation");
  await expect(
    api.qualifiedExportDownload(workspace, metadata.id, "csv"),
  ).rejects.toThrow("invalid export file");
});
it("exports only confirmed records and blocks repeat clicks while pending", async () => {
  const save = vi
    .spyOn(files, "saveQualifiedExport")
    .mockImplementation(() => {});
  const create = vi.fn().mockResolvedValue(metadata);
  let resolve!: (blob: Blob) => void;
  const download = vi.fn().mockImplementation(
    () =>
      new Promise<Blob>((r) => {
        resolve = r;
      }),
  );
  const api = {
    ...createApi(),
    qualifiedExport: create,
    qualifiedExportDownload: download,
  };
  const view = render(
    <QualifiedExportPanel
      api={api}
      workspaceId={workspace}
      planId={plan}
      candidates={[
        confirmed,
        {
          ...confirmed,
          id: plan,
          fit: { status: "near_match" },
        } as ResearchCandidate,
      ]}
    />,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Download confirmed CSV" }),
  );
  await waitFor(() => expect(download).toHaveBeenCalledTimes(1));
  expect(create.mock.calls[0].slice(0, 4)).toEqual([
    workspace,
    plan,
    [entity],
    "csv",
  ]);
  expect(
    screen.getByRole("button", { name: "Preparing download…" }),
  ).toBeDisabled();
  await act(async () => resolve(new Blob(["file"])));
  expect(save).toHaveBeenCalledTimes(1);
  view.unmount();
});
it("discards a late export after plan scope changes", async () => {
  const save = vi
    .spyOn(files, "saveQualifiedExport")
    .mockImplementation(() => {});
  let resolve!: (value: typeof metadata) => void;
  const create = vi.fn().mockImplementation(
    () =>
      new Promise<typeof metadata>((r) => {
        resolve = r;
      }),
  );
  const download = vi.fn();
  const api = {
    ...createApi(),
    qualifiedExport: create,
    qualifiedExportDownload: download,
  };
  const view = render(
    <QualifiedExportPanel
      api={api}
      workspaceId={workspace}
      planId={plan}
      candidates={[confirmed]}
    />,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Download confirmed CSV" }),
  );
  view.rerender(
    <QualifiedExportPanel
      api={api}
      workspaceId={workspace}
      planId={entity}
      candidates={[confirmed]}
    />,
  );
  await act(async () => resolve(metadata));
  expect(create.mock.calls[0][4].aborted).toBe(true);
  expect(download).not.toHaveBeenCalled();
  expect(save).not.toHaveBeenCalled();
  view.unmount();
});

it("cancels a stalled file download without returning partial bytes", async () => {
  vi.useFakeTimers();
  try {
    const cancel = vi.fn();
    const api = createQualifiedExportClient(
      vi
        .fn()
        .mockResolvedValue(
          new Response(new ReadableStream({ cancel }), {
            headers: { "Content-Type": "text/csv" },
          }),
        ),
    );
    const result = api.qualifiedExportDownload(workspace, metadata.id, "csv");
    const assertion = expect(result).rejects.toThrow("timed out");
    await vi.advanceTimersByTimeAsync(15001);
    await assertion;
    expect(cancel).toHaveBeenCalled();
  } finally {
    vi.useRealTimers();
  }
});
