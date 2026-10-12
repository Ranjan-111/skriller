// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import { createApi, type JobSnapshot } from "../src/lib/api";

const identity = { workspace_id: "workspace/1", job_id: "job/1" };
const event = (id = "1", kind = "state_changed") =>
  `id: ${id}\nevent: progress\ndata: ${JSON.stringify({ kind, details: { state: "running" } })}\n\n`;
const streamResponse = (text: string) =>
  new Response(text, {
    headers: { "Content-Type": "text/event-stream; charset=utf-8" },
  });

describe("workspace progress transport", () => {
  it("reads the actual workspace-scoped snapshot with Bearer authentication", async () => {
    const snapshot: JobSnapshot = {
      id: "job-id",
      workspace_id: "workspace-id",
      state: "running",
      stage: "discovering",
      version: 2,
      terminal_reason: null,
    };
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(snapshot)));
    expect(
      await createApi(
        "http://api",
        fetcher,
        async () => "private-token",
      ).snapshot(identity),
    ).toEqual(snapshot);
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe("http://api/v1/workspaces/workspace%2F1/jobs/job%2F1");
    expect(url).not.toContain("private-token");
    expect(init.headers.get("Authorization")).toBe("Bearer private-token");
  });

  it("resumes through Last-Event-ID and Authorization headers, without URL credentials", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(streamResponse(event("9007199254740993")));
    const api = createApi("http://api", fetcher, async () => "private-token");
    const updates = [];
    for await (const update of api.progressEvents(identity, {
      lastEventId: "9007199254740992",
    }))
      updates.push(update);
    expect(updates).toEqual([
      {
        id: "9007199254740993",
        data: { kind: "state_changed", details: { state: "running" } },
      },
    ]);
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe(
      "http://api/v1/workspaces/workspace%2F1/jobs/job%2F1/events",
    );
    expect(new URL(url).search).toBe("");
    expect(init.headers.get("Last-Event-ID")).toBe("9007199254740992");
    expect(init.headers.get("Authorization")).toBe("Bearer private-token");
    expect(init.headers.get("Accept")).toBe("text/event-stream");
  });

  it("decodes fragmented CRLF frames, ignores heartbeats and preserves incomplete EOF", async () => {
    const text =
      ": heartbeat\r\n\r\n" +
      event().replaceAll("\n", "\r\n") +
      "id: 2\nevent: progress\ndata: incomplete";
    const body = new ReadableStream({
      start(controller) {
        for (const piece of [
          text.slice(0, 20),
          text.slice(20, 45),
          text.slice(45),
        ])
          controller.enqueue(new TextEncoder().encode(piece));
        controller.close();
      },
    });
    const api = createApi(
      "http://api",
      vi.fn().mockResolvedValue(
        new Response(body, {
          headers: { "Content-Type": "text/event-stream" },
        }),
      ),
    );
    const updates = [];
    for await (const update of api.progressEvents(identity))
      updates.push(update);
    expect(updates).toHaveLength(1);
    expect(updates[0].id).toBe("1");
  });

  it.each(["-1", "1e2", "9223372036854775808", "1\r\nAuthorization: bad"])(
    "rejects invalid replay cursor %s before fetching",
    async (cursor) => {
      const fetcher = vi.fn();
      await expect(
        createApi("http://api", fetcher).progress(identity, {
          lastEventId: cursor,
        }),
      ).rejects.toThrow("Invalid progress cursor");
      expect(fetcher).not.toHaveBeenCalled();
    },
  );

  it("returns authentication errors without reading a fabricated stream", async () => {
    await expect(
      createApi(
        "http://api",
        vi.fn().mockResolvedValue(new Response("", { status: 401 })),
      ).progress(identity),
    ).rejects.toThrow("Sign in");
  });

  it("rejects a JSON response masquerading as successful streaming", async () => {
    await expect(
      createApi(
        "http://api",
        vi.fn().mockResolvedValue(
          new Response("{}", {
            headers: { "Content-Type": "application/json" },
          }),
        ),
      ).progress(identity),
    ).rejects.toThrow("unexpected progress stream");
  });

  it("rejects malformed event payloads instead of treating them as progress", async () => {
    const api = createApi(
      "http://api",
      vi
        .fn()
        .mockResolvedValue(
          streamResponse(
            'id: 1\nevent: progress\ndata: {"kind": "started", "details": null}\n\n',
          ),
        ),
    );
    await expect(async () => {
      for await (const _update of api.progressEvents(identity)) {
        /* consume */
      }
    }).rejects.toThrow("Invalid progress event");
  });

  it("bounds unterminated frames so invalid streams cannot grow memory indefinitely", async () => {
    const api = createApi(
      "http://api",
      vi.fn().mockResolvedValue(streamResponse("data: " + "x".repeat(65_537))),
    );
    await expect(async () => {
      for await (const _update of api.progressEvents(identity)) {
        /* consume */
      }
    }).rejects.toThrow("exceeds its limit");
  });

  it("cancels the reader when a consumer leaves the stream", async () => {
    const cancel = vi.fn();
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(event()));
      },
      cancel,
    });
    const api = createApi(
      "http://api",
      vi.fn().mockResolvedValue(
        new Response(body, {
          headers: { "Content-Type": "text/event-stream" },
        }),
      ),
    );
    for await (const _update of api.progressEvents(identity)) break;
    expect(cancel).toHaveBeenCalledTimes(1);
  });

  it("passes caller cancellation through to the fetch stream", async () => {
    const controller = new AbortController();
    const fetcher = vi.fn().mockResolvedValue(streamResponse(event()));
    await createApi("http://api", fetcher).progress(identity, {
      signal: controller.signal,
    });
    const signal = fetcher.mock.calls[0][1].signal as AbortSignal;
    expect(signal.aborted).toBe(false);
    controller.abort();
    expect(signal.aborted).toBe(true);
  });
});

it("refreshes an expired app token before resuming while keeping the exact cursor header", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(new Response("", { status: 401 }))
    .mockResolvedValueOnce(streamResponse(event("43")));
  const token = vi
    .fn()
    .mockResolvedValueOnce("expired-token")
    .mockResolvedValueOnce("new-token");
  const api = createApi("http://api", fetcher, token);
  const updates = [];
  for await (const update of api.progressEvents(identity, {
    lastEventId: "42",
  }))
    updates.push(update);
  expect(updates[0].id).toBe("43");
  expect(token.mock.calls).toEqual([[], [true]]);
  expect(fetcher.mock.calls[1][1].headers.get("Last-Event-ID")).toBe("42");
  expect(fetcher.mock.calls[1][1].headers.get("Authorization")).toBe(
    "Bearer new-token",
  );
  expect(String(fetcher.mock.calls[1][0])).not.toContain("token");
});
