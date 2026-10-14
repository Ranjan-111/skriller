import { describe, expect, it, vi } from "vitest";
import { createApi } from "../src/lib/api";
const response = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
describe("research service client", () => {
  it("loads a saved scoped interpretation and rejects a mismatched job", async () => {
    const view = {
      job_id: "j1",
      plan_id: "p1",
      workspace_id: "w1",
      status: "ready",
      interpretation: {
        schema_version: 1,
        workspace_id: "w1",
        conversation_id: "c1",
        revision: 1,
        entity_type: "company",
        must_have: [
          { field: "location", operator: "contains", value: "Berlin" },
        ],
        preferences: [],
        exclusions: [],
        requested_fields: [],
        sources: ["web"],
        freshness_days: null,
        unsupported_criteria: [],
        clarification: null,
        limits: { max_results: 25 },
      },
    };
    const fetcher = vi.fn().mockResolvedValue(response(view));
    await expect(
      createApi("http://api", fetcher).plan("j1", "w1"),
    ).resolves.toEqual(view);
    expect(fetcher.mock.calls[0][0]).toBe(
      "http://api/v1/jobs/j1/plan?workspace_id=w1",
    );
    const mismatch = vi
      .fn()
      .mockResolvedValue(response({ ...view, job_id: "j2" }));
    await expect(
      createApi("http://api", mismatch).plan("j1", "w1"),
    ).rejects.toThrow("unexpected plan details");
  });
  it("loads tenant-scoped usage and rejects malformed or mismatched amounts", async () => {
    const usage = {
      job_id: "j1",
      workspace_id: "w1",
      currency: "USD",
      budget_cap_usd: "1",
      confirmed_cost_usd: "0.03",
      estimated_cost_usd: "0.2",
      reserved_cost_usd: "0.1",
      exposure_ceiling_usd: "0.33",
      remaining_budget_usd: "0.67",
      dimensions: {
        confirmed: { search_calls: 1 },
        estimated: {},
        reserved: {},
      },
      stage_metrics: [],
      invalid_stage_observations: 0,
      stage_metrics_truncated: false,
    };
    const fetcher = vi.fn().mockResolvedValue(response(usage));
    await expect(
      createApi("http://api", fetcher).usage("j1", "w1"),
    ).resolves.toEqual(usage);
    expect(fetcher.mock.calls[0][0]).toBe(
      "http://api/v1/jobs/j1/usage?workspace_id=w1",
    );
    const mismatch = vi
      .fn()
      .mockResolvedValue(response({ ...usage, workspace_id: "w2" }));
    await expect(
      createApi("http://api", mismatch).usage("j1", "w1"),
    ).rejects.toThrow("unexpected run usage");
  });
  it("cancels only the requested workspace run using the app bearer token", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        response({ id: "j1", workspace_id: "w1", state: "cancelled" }),
      );
    await createApi("http://api", fetcher, async () => "test-token").cancel(
      "j1",
      "w1",
    );
    expect(fetcher.mock.calls[0][0]).toBe(
      "http://api/v1/jobs/j1/cancel?workspace_id=w1",
    );
    expect(fetcher.mock.calls[0][1].method).toBe("POST");
    expect(fetcher.mock.calls[0][1].headers.get("Authorization")).toBe(
      "Bearer test-token",
    );
  });
  it("does not confirm cancellation for another run or workspace", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        response({ id: "j2", workspace_id: "w2", state: "cancelled" }),
      );
    await expect(
      createApi("http://api", fetcher).cancel("j1", "w1"),
    ).rejects.toThrow("not confirmed");
  });
  it("resumes the scoped job with an idempotency key and checks the queue response", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        response({ id: "j1", workspace_id: "w1", state: "queued" }),
      );
    await createApi("http://api", fetcher, async () => "test-token").resume(
      "j1",
      "w1",
    );
    expect(fetcher.mock.calls[0][0]).toBe(
      "http://api/v1/jobs/j1/resume?workspace_id=w1",
    );
    expect(fetcher.mock.calls[0][1].method).toBe("POST");
    expect(fetcher.mock.calls[0][1].headers.get("Authorization")).toBe(
      "Bearer test-token",
    );
    expect(fetcher.mock.calls[0][1].headers.get("Idempotency-Key")).toMatch(
      /^[\da-f-]{36}$/i,
    );
  });
  it("keeps a server-rejected unsafe resume visible", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(response({ detail: "blocked" }, 409));
    await expect(
      createApi("http://api", fetcher).resume("j1", "w1"),
    ).rejects.toThrow("cannot safely resume");
  });
  it("loads typed readiness for the requested workspace", async () => {
    const data = [
      {
        capability: {
          source: "linkedin",
          operation: "read",
          engineering_status: "planned",
          operational_status: "needs_connection",
          auth_kind: "session",
          access_route: "Dedicated adapter unavailable",
          version: "unimplemented",
          allowed_fields: [],
        },
        disabled: false,
        setup_state: "needs_connection",
        evidence_scope: "dedicated_adapter",
        credential_validation: "not_performed",
      },
    ];
    const fetcher = vi.fn().mockResolvedValue(response(data));
    await expect(
      createApi("http://api", fetcher).sourceDiagnostics("w /1"),
    ).resolves.toEqual(data);
    expect(fetcher.mock.calls[0][0]).toBe(
      "http://api/v1/workspaces/w%20%2F1/sources",
    );
  });
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
    results: [
      {
        id: "r1",
        title: "Company",
        url: "https://example.com",
        snippet: "Public source",
        source: "web",
        provider: "exa_keyless",
        evidence_kind: "search_snippet",
        qualification: "unverified",
        observed_at: "2026-10-12T00:00:00Z",
        provenance: [
          {
            source: "web",
            original_url: "https://search.example/result/1",
            query: "company",
            rank: 1,
            provider: "exa_keyless",
            observed_at: "2026-10-12T00:00:00Z",
            evidence_kind: "search_snippet",
          },
        ],
      },
    ],
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

it.each([
  { collection: { status: "read", failure_code: null, network_seconds: -1 } },
  {
    extraction: {
      status: "observed",
      failure_code: null,
      rejected_claims: 0,
      coverage_complete: true,
      omitted_chunks: 0,
      observations: [
        {
          claim_id: "c1",
          field: "name",
          value: {},
          quote: "Source text",
          status: "unverified",
        },
      ],
    },
  },
])("rejects malformed page evidence before rendering", async (extra) => {
  const payload = {
    job_id: "j1",
    workspace_id: "w1",
    state: "completed",
    limitations: [],
    results: [
      {
        id: "r1",
        title: "Company",
        url: "https://example.com",
        snippet: "Source",
        source: "web",
        provider: "exa_keyless",
        evidence_kind: "search_snippet",
        qualification: "unverified",
        observed_at: "2026-10-14T00:00:00Z",
        provenance: [],
        ...extra,
      },
    ],
  };
  const fetcher = vi.fn().mockResolvedValue(response(payload));
  await expect(
    createApi("http://api", fetcher).results("j1", "w1"),
  ).rejects.toThrow("unexpected results");
});
it("rejects malformed search provenance instead of rendering it as evidence", async () => {
  const fetcher = vi.fn().mockResolvedValue(
    response({
      job_id: "j1",
      workspace_id: "w1",
      state: "completed",
      limitations: [],
      results: [
        {
          id: "r1",
          title: "Company",
          url: "https://example.com",
          snippet: "Snippet",
          source: "web",
          provider: "exa_keyless",
          evidence_kind: "search_snippet",
          qualification: "unverified",
          observed_at: "2026-10-12T00:00:00Z",
          provenance: [
            {
              source: "web",
              original_url: "https://example.com",
              query: "x",
              rank: "1",
            },
          ],
        },
      ],
    }),
  );
  await expect(
    createApi("http://api", fetcher).results("j1", "w1"),
  ).rejects.toThrow("unexpected results");
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

it("explains workspace ceilings without retrying or losing the prompt", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(
      new Response("{}", {
        status: 422,
        headers: { "X-Skriller-Failure": "entitlement_limits" },
      }),
    );
  await expect(
    createApi("http://api", fetcher).results("j1", "w1"),
  ).rejects.toThrow("Adjust the options");
  expect(fetcher).toHaveBeenCalledTimes(1);
});
