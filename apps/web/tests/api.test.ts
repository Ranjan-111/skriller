import { describe, expect, it, vi } from "vitest";
import { createApi } from "../src/lib/api";
const response = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
describe("research service client", () => {
  it("checks liveness and readiness separately", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(response({}))
      .mockResolvedValueOnce(response({}, 503));
    expect(await createApi("http://api/", fetcher).health()).toEqual({
      live: true,
      ready: false,
    });
    expect(fetcher.mock.calls.map((call) => call[0])).toEqual([
      "http://api/health/live",
      "http://api/health/ready",
    ]);
  });
  it("uses the conversation/message contract and encodes IDs", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(response({ id: "conversation/1" }))
      .mockResolvedValueOnce(
        response({ message_id: "m1", plan_id: "p1", job_id: "job1" }),
      );
    const api = createApi("http://api", fetcher, async () => "user-token");
    expect(
      await api.submit({
        prompt: "Find founders",
        mode: "leads",
        sources: ["linkedin"],
        result_limit: 25,
      }),
    ).toEqual({ id: "job1", status: "accepted" });
    expect(fetcher.mock.calls[1][0]).toBe(
      "http://api/v1/conversations/conversation%2F1/messages",
    );
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({
      content: "Find founders",
      options: { mode: "leads", sources: ["linkedin"], result_limit: 25 },
    });
    expect(fetcher.mock.calls[0][1].headers.get("Authorization")).toBe(
      "Bearer user-token",
    );
  });
  it.each([404, 501, 503])(
    "surfaces unavailable execution (%s), never fabricated jobs",
    async (status) => {
      const fetcher = vi.fn().mockResolvedValue(response({}, status));
      await expect(
        createApi("http://api", fetcher).submit({
          prompt: "Find founders",
          mode: "leads",
          sources: ["web"],
          result_limit: 10,
        }),
      ).rejects.toThrow("not available yet");
      expect(fetcher).toHaveBeenCalledTimes(1);
    },
  );
  it.each([401, 403])(
    "requires sign-in for authentication error (%s)",
    async (status) => {
      await expect(
        createApi(
          "http://api",
          vi.fn().mockResolvedValue(response({}, status)),
        ).submit({
          prompt: "Find founders",
          mode: "leads",
          sources: ["web"],
          result_limit: 10,
        }),
      ).rejects.toThrow("Sign in");
    },
  );
  it("rejects malformed successful payloads", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(response({ id: "c1" }))
      .mockResolvedValueOnce(response({ count: 10 }));
    await expect(
      createApi("http://api", fetcher).submit({
        prompt: "Find founders",
        mode: "leads",
        sources: ["web"],
        result_limit: 10,
      }),
    ).rejects.toThrow("No run has been confirmed");
  });
  it("surfaces network failure without confirming readiness", async () => {
    await expect(
      createApi(
        "http://api",
        vi.fn().mockRejectedValue(new TypeError("network")),
      ).health(),
    ).rejects.toThrow("Cannot reach");
  });
  it("shows planner clarification rather than accepting a job", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(response({ id: "c1" }))
      .mockResolvedValueOnce(
        response({ clarification: "Headquarters or founder location?" }),
      );
    await expect(
      createApi("http://api", fetcher).submit({
        prompt: "Find founders",
        mode: "leads",
        sources: ["web"],
        result_limit: 10,
      }),
    ).rejects.toThrow("Headquarters or founder location?");
  });
});

it("refreshes a rejected token once and resends headers without URL credentials", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(response({}, 401))
    .mockResolvedValueOnce(response({ id: "c1" }))
    .mockResolvedValueOnce(response({ job_id: "job1" }));
  const token = vi
    .fn()
    .mockResolvedValueOnce("expired-token")
    .mockResolvedValueOnce("refreshed-token")
    .mockResolvedValueOnce("refreshed-token");
  await createApi("http://api", fetcher, token).submit({
    prompt: "Find founders",
    mode: "leads",
    sources: ["web"],
    result_limit: 10,
  });
  expect(token.mock.calls).toEqual([[], [true], []]);
  expect(fetcher.mock.calls[1][1].headers.get("Authorization")).toBe(
    "Bearer refreshed-token",
  );
  expect(
    fetcher.mock.calls.every((call) => !String(call[0]).includes("token")),
  ).toBe(true);
});
it("does not loop refresh when the replacement token is also rejected", async () => {
  const fetcher = vi.fn().mockResolvedValue(response({}, 401));
  const token = vi.fn().mockResolvedValue("invalid-token");
  await expect(
    createApi("http://api", fetcher, token).snapshot({
      workspace_id: "w1",
      job_id: "j1",
    }),
  ).rejects.toThrow("Sign in");
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(token.mock.calls).toEqual([[], [true]]);
});
it("redacts token refresh failures rather than leaking SDK credentials", async () => {
  const fetcher = vi.fn().mockResolvedValue(response({}, 401));
  const token = vi
    .fn()
    .mockResolvedValueOnce("expired-token")
    .mockRejectedValueOnce(new Error("secret-token raw SDK error"));
  await expect(
    createApi("http://api", fetcher, token).snapshot({
      workspace_id: "w1",
      job_id: "j1",
    }),
  ).rejects.toThrow("Sign in again");
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("loads workspace-scoped run results and rejects another workspace's response", async () => {
  const payload = {
    job_id: "j/1",
    workspace_id: "w/1",
    state: "completed",
    results: [],
    limitations: ["Snippets only"],
  };
  const fetcher = vi.fn().mockImplementation(async () => response(payload));
  const api = createApi("http://api", fetcher, async () => "token");
  expect(await api.results("j/1", "w/1")).toEqual(payload);
  expect(fetcher.mock.calls[0][0]).toBe(
    "http://api/v1/jobs/j%2F1/results?workspace_id=w%2F1",
  );
  await expect(api.results("j/1", "another-workspace")).rejects.toThrow(
    "unexpected results",
  );
});
it("rejects malformed candidates rather than presenting them as research evidence", async () => {
  const fetcher = vi.fn().mockResolvedValue(
    response({
      job_id: "j1",
      workspace_id: "w1",
      state: "completed",
      results: [{ title: "Invented lead" }],
      limitations: [],
    }),
  );
  await expect(
    createApi("http://api", fetcher).results("j1", "w1"),
  ).rejects.toThrow("unexpected results");
});

it("retains the workspace identity provided on accepted research", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(response({ id: "c1" }))
    .mockResolvedValueOnce(response({ job_id: "j1", workspace_id: "w1" }));
  expect(
    await createApi("http://api", fetcher).submit({
      prompt: "Find companies",
      mode: "leads",
      sources: ["web"],
      result_limit: 10,
    }),
  ).toEqual({ id: "j1", workspace_id: "w1", status: "accepted" });
});
