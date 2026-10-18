import { describe, expect, it, vi } from "vitest";
import { createApi } from "../src/lib/api";
const response = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });

const fitView = () => ({
  job_id: "j1",
  workspace_id: "w1",
  state: "completed",
  limitations: [],
  groups: {
    confirmed: ["e1"],
    near_match: [] as string[],
    excluded: [],
    unverified: [],
  },
  results: [
    {
      id: "e1",
      title: "Synthetic company",
      url: "https://example.org/company",
      snippet: "Indexed reference",
      source: "web",
      provider: "exa_keyless",
      evidence_kind: "search_snippet",
      qualification: "unverified",
      observed_at: "2026-10-14T00:00:00Z",
      provenance: [],
      fit: {
        status: "confirmed",
        preference_score: 0,
        limitations: [],
        exclusions: [],
        preferences: [],
        essential: [
          {
            criterion: { field: "employee_count", operator: "gte", value: 10 },
            outcome: "matched",
            reason: "supported_by_accepted_fact",
            evidence_ids: ["00000000-0000-0000-0000-000000000001"],
          },
        ],
      },
    },
  ],
});

const redditThreadView = () => ({
  evidence_id: "00000000-0000-4000-8000-000000000062",
  rejected_signals: 0,
  signal_coverage_complete: true,
  signals: [
    {
      resource_id: "t1_comment",
      quote: "We still coordinate this manually.",
      source_url:
        "https://www.reddit.com/r/synthetic/comments/postabc/thread-title/comment/",
      published_at: "2026-10-14T00:00:00Z",
      status: "source_specific_unverified",
      buying_intent: "not_inferred",
    },
  ],
  thread: {
    source: "reddit",
    evidence_kind: "post_comment_read",
    observed_at: "2026-10-14T01:00:00Z",
    coverage_complete: false,
    omitted_comments: 1,
    unexpanded_nodes: 0,
    buying_intent: "not_inferred",
    subject_identity: "unknown",
    post: {
      native_id: "t3_postabc",
      source_url:
        "https://www.reddit.com/r/synthetic/comments/postabc/thread-title/",
      title: "Synthetic workflow question",
      subreddit: "synthetic",
      author_handle: "example_handle",
      author_identity: "unknown",
      excerpt: "How do you handle operations?",
      content_unavailable: false,
      truncated: false,
      published_at: "2026-10-13T00:00:00Z",
    },
    comments: [
      {
        native_id: "t1_comment",
        parent_id: "t3_postabc",
        source_url:
          "https://www.reddit.com/r/synthetic/comments/postabc/thread-title/comment/",
        text: "We still coordinate this manually.",
        author_handle: null,
        author_identity: "unknown",
        published_at: "2026-10-14T00:00:00Z",
        content_unavailable: false,
        truncated: false,
      },
      {
        native_id: "t1_deleted",
        parent_id: "t1_comment",
        source_url:
          "https://www.reddit.com/r/synthetic/comments/postabc/thread-title/deleted/",
        text: "",
        author_handle: null,
        author_identity: "unknown",
        published_at: null,
        content_unavailable: true,
        truncated: false,
      },
    ],
  },
});

const linkedinReadView = (
  kind: "profile" | "company" | "post" = "profile",
) => ({
  evidence_id: "00000000-0000-4000-8000-000000000063",
  resource: {
    source: "linkedin",
    evidence_kind: "resource_section_read",
    resource_kind: kind,
    source_url:
      kind === "profile"
        ? "https://www.linkedin.com/in/synthetic-person/"
        : kind === "company"
          ? "https://www.linkedin.com/company/synthetic-company/about/"
          : "https://www.linkedin.com/feed/update/urn:li:activity:123456/",
    section:
      kind === "profile"
        ? "main_profile"
        : kind === "company"
          ? "about"
          : "post",
    text: "Synthetic source section text.",
    text_truncated: false,
    observed_at: "2026-10-14T01:00:00Z",
    coverage_complete: false,
    subject_identity: "unknown",
    contact_details: "unavailable",
    buying_intent: "not_inferred",
  },
});

it("preserves evidence-backed fit separately from an unverified indexed reference", async () => {
  const view = fitView();
  const api = createApi(
    "http://api",
    vi.fn().mockResolvedValue(response(view)),
  );
  const result = await api.results("j1", "w1");
  expect(result.results[0].fit?.status).toBe("confirmed");
  expect(result.results[0].qualification).toBe("unverified");
});

it("accepts bounded Reddit thread evidence and rejects invented or misbound signals", async () => {
  const valid = fitView();
  const candidate = valid.results[0] as Record<string, unknown>;
  candidate.source = "reddit";
  candidate.provider = "reddit_oauth";
  candidate.evidence_kind = "public_post";
  candidate.url =
    "https://www.reddit.com/r/synthetic/comments/postabc/thread-title/";
  candidate.reddit_thread = redditThreadView();
  const api = createApi(
    "http://api",
    vi.fn().mockResolvedValue(response(valid)),
  );
  expect(
    (await api.results("j1", "w1")).results[0].reddit_thread?.signals,
  ).toHaveLength(1);

  for (const corrupt of [
    (view: ReturnType<typeof redditThreadView>) => {
      view.signals[0].quote = "A quote absent from the comment.";
    },
    (view: ReturnType<typeof redditThreadView>) => {
      view.signals[0].source_url = "https://www.reddit.com/r/other/comments/x/";
    },
    (view: ReturnType<typeof redditThreadView>) => {
      view.thread.comments[1].parent_id = "t1_missing";
    },
    (view: ReturnType<typeof redditThreadView>) => {
      view.thread.comments[1].content_unavailable = true;
      view.thread.comments[1].text = "removed text must not remain";
    },
  ]) {
    const invalid = fitView();
    const invalidCandidate = invalid.results[0] as Record<string, unknown>;
    invalidCandidate.source = "reddit";
    invalidCandidate.provider = "reddit_oauth";
    invalidCandidate.evidence_kind = "public_post";
    invalidCandidate.url = candidate.url;
    const thread = redditThreadView();
    corrupt(thread);
    invalidCandidate.reddit_thread = thread;
    const invalidApi = createApi(
      "http://api",
      vi.fn().mockResolvedValue(response(invalid)),
    );
    await expect(invalidApi.results("j1", "w1")).rejects.toThrow(
      "unexpected results",
    );
  }
});

it("rejects Reddit thread evidence attached to another source", async () => {
  const view = fitView();
  (view.results[0] as Record<string, unknown>).reddit_thread =
    redditThreadView();
  const api = createApi(
    "http://api",
    vi.fn().mockResolvedValue(response(view)),
  );
  await expect(api.results("j1", "w1")).rejects.toThrow("unexpected results");
});

it("accepts typed LinkedIn reads only when resource and candidate identities match", async () => {
  for (const kind of ["profile", "company", "post"] as const) {
    const view = fitView();
    const candidate = view.results[0] as Record<string, unknown>;
    candidate.source = "linkedin";
    candidate.provider = "linkedin_mcp";
    candidate.evidence_kind = "search_reference";
    candidate.url = linkedinReadView(kind).resource.source_url;
    if (kind === "company")
      candidate.url = "https://www.linkedin.com/company/synthetic-company";
    candidate.linkedin_read = linkedinReadView(kind);
    const api = createApi(
      "http://api",
      vi.fn().mockResolvedValue(response(view)),
    );
    expect(
      (await api.results("j1", "w1")).results[0].linkedin_read?.resource
        .resource_kind,
    ).toBe(kind);
  }

  for (const corrupt of [
    (resource: Record<string, unknown>) => {
      resource.source_url = "https://www.linkedin.com/in/another-person/";
    },
    (resource: Record<string, unknown>) => {
      resource.text = "x".repeat(16385);
    },
    (resource: Record<string, unknown>) => {
      resource.contact_details = "visible";
    },
    (resource: Record<string, unknown>) => {
      resource.section = "about";
    },
    (resource: Record<string, unknown>) => {
      resource.resource_kind = "company";
      resource.section = "about";
    },
    (resource: Record<string, unknown>) => {
      resource.observed_at = "2026-10-14T01:00:00";
    },
    (resource: Record<string, unknown>) => {
      resource.source_url = "https://www.linkedin.com/in/synthetic-person";
    },
  ]) {
    const view = fitView();
    const candidate = view.results[0] as Record<string, unknown>;
    candidate.source = "linkedin";
    candidate.provider = "linkedin_mcp";
    candidate.evidence_kind = "search_reference";
    candidate.url = "https://www.linkedin.com/in/synthetic-person/";
    const read = linkedinReadView();
    corrupt(read.resource);
    candidate.linkedin_read = read;
    const api = createApi(
      "http://api",
      vi.fn().mockResolvedValue(response(view)),
    );
    await expect(api.results("j1", "w1")).rejects.toThrow("unexpected results");
  }
});

it("accepts legacy results without resume readiness but rejects unknown readiness values", async () => {
  const legacy = fitView();
  const api = createApi(
    "http://api",
    vi.fn().mockResolvedValue(response(legacy)),
  );
  expect(await api.results("j1", "w1")).not.toHaveProperty("resume_status");

  const invalid = { ...fitView(), resume_status: "maybe" };
  const invalidApi = createApi(
    "http://api",
    vi.fn().mockResolvedValue(response(invalid)),
  );
  await expect(invalidApi.results("j1", "w1")).rejects.toThrow(
    "unexpected results",
  );
});

it("accepts only honest indexed LinkedIn and Reddit access metadata", async () => {
  const valid = fitView();
  const candidate: Record<string, unknown> = valid.results[0];
  candidate.source = "linkedin";
  candidate.platform_reference = {
    source: "linkedin",
    resource_kind: "profile",
    discovery_backend: "exa_keyless",
    access: "indexed_reference_only",
    direct_read_status: "not_attempted",
    subject_identity: "unknown",
  };
  const api = createApi(
    "http://api",
    vi.fn().mockResolvedValue(response(valid)),
  );
  expect(
    (await api.results("j1", "w1")).results[0].platform_reference?.source,
  ).toBe("linkedin");

  (candidate.platform_reference as Record<string, unknown>).direct_read_status =
    "success" as "not_attempted";
  const unsafe = createApi(
    "http://api",
    vi.fn().mockResolvedValue(response(valid)),
  );
  await expect(unsafe.results("j1", "w1")).rejects.toThrow(
    "unexpected results",
  );
});

it("accepts connected LinkedIn search references only with matching provenance", async () => {
  const valid = fitView();
  const candidate = valid.results[0] as Record<string, unknown>;
  candidate.source = "linkedin";
  candidate.provider = "linkedin_mcp";
  candidate.evidence_kind = "search_reference";
  candidate.url = "https://www.linkedin.com/in/synthetic-person";
  candidate.platform_reference = {
    source: "linkedin",
    resource_kind: "profile",
    discovery_backend: "linkedin_mcp",
    access: "connected_search_reference_only",
    direct_read_status: "not_attempted",
    subject_identity: "unknown",
  };
  candidate.provenance = [
    {
      source: "linkedin",
      original_url: candidate.url,
      query: "synthetic researcher",
      rank: 1,
      provider: "linkedin_mcp",
      observed_at: "2026-10-14T00:00:00Z",
      evidence_kind: "search_reference",
    },
  ];
  const api = createApi(
    "http://api",
    vi.fn().mockResolvedValue(response(valid)),
  );
  expect((await api.results("j1", "w1")).results[0]).toMatchObject({
    provider: "linkedin_mcp",
    evidence_kind: "search_reference",
    platform_reference: {
      access: "connected_search_reference_only",
      direct_read_status: "not_attempted",
      subject_identity: "unknown",
    },
  });

  candidate.source = "reddit";
  const mixed = createApi(
    "http://api",
    vi.fn().mockResolvedValue(response(valid)),
  );
  await expect(mixed.results("j1", "w1")).rejects.toThrow("unexpected results");
});

it.each([
  ["backend", { discovery_backend: "exa_keyless" }],
  ["access", { access: "indexed_reference_only" }],
  ["source", { source: "reddit" }],
  ["read status", { direct_read_status: "success" }],
  ["identity", { subject_identity: "verified" }],
])(
  "rejects mixed connected LinkedIn reference metadata: %s",
  async (_name, patch) => {
    const valid = fitView();
    const candidate = valid.results[0] as Record<string, unknown>;
    candidate.source = "linkedin";
    candidate.provider = "linkedin_mcp";
    candidate.evidence_kind = "search_reference";
    candidate.platform_reference = {
      source: "linkedin",
      resource_kind: "profile",
      discovery_backend: "linkedin_mcp",
      access: "connected_search_reference_only",
      direct_read_status: "not_attempted",
      subject_identity: "unknown",
      ...patch,
    };
    const api = createApi(
      "http://api",
      vi.fn().mockResolvedValue(response(valid)),
    );
    await expect(api.results("j1", "w1")).rejects.toThrow("unexpected results");
  },
);

it("accepts bounded YouTube public metadata and timestamped caption evidence", async () => {
  const view = fitView();
  (view.results[0] as Record<string, unknown>).youtube = {
    metadata: {
      source: "youtube",
      evidence_kind: "public_video_metadata",
      counter_scope: "public_metadata",
      title: "Public demo",
      channel: "Example channel",
      channel_url: "https://www.youtube.com/@example",
      description: "Synthetic public description",
      duration_seconds: 125.5,
      view_count: 4200,
      like_count: null,
      observed_at: "2026-10-14T00:00:00Z",
      published_on: "2026-10-10",
      source_url: "https://www.youtube.com/watch?v=BaW_jenozKc",
      transcript_languages: ["en"],
      transcript_state: "available",
    },
    metadata_truncated: false,
    caption_status: "retrieved",
    caption_origin: "provided",
    caption_language: "en",
    segments: [
      {
        claim_id: "00000000-0000-0000-0000-000000000001",
        evidence_id: "00000000-0000-0000-0000-000000000002",
        start_seconds: 1.25,
        end_seconds: 3.5,
        text: "Synthetic caption cue",
      },
    ],
    omitted_segments: 0,
    subject_identity: "unknown",
    evidence_expired: false,
  };
  const api = createApi(
    "http://api",
    vi.fn().mockResolvedValue(response(view)),
  );
  const result = await api.results("j1", "w1");
  expect(result.results[0].youtube?.metadata?.view_count).toBe(4200);
  expect(result.results[0].youtube?.segments[0].start_seconds).toBe(1.25);
});

it.each([
  [
    "identity",
    (youtube: Record<string, unknown>) =>
      (youtube.subject_identity = "verified"),
  ],
  [
    "negative public counter",
    (youtube: Record<string, unknown>) => {
      (youtube.metadata as Record<string, unknown>).view_count = -1;
    },
  ],
  [
    "unsafe metadata host",
    (youtube: Record<string, unknown>) => {
      (youtube.metadata as Record<string, unknown>).source_url =
        "https://example.org/video";
    },
  ],
  [
    "unbounded segment",
    (youtube: Record<string, unknown>) => {
      youtube.segments = Array(21).fill((youtube.segments as unknown[])[0]);
    },
  ],
])("rejects unsafe YouTube result payloads: %s", async (_name, change) => {
  const view = fitView();
  const youtube = {
    metadata: {
      source: "youtube",
      evidence_kind: "public_video_metadata",
      counter_scope: "public_metadata",
      title: "Public demo",
      channel: null,
      channel_url: null,
      description: null,
      duration_seconds: null,
      view_count: 4,
      like_count: null,
      observed_at: "2026-10-14T00:00:00Z",
      published_on: null,
      source_url: "https://youtu.be/BaW_jenozKc",
      transcript_languages: ["en"],
      transcript_state: "available",
    },
    metadata_truncated: false,
    caption_status: "retrieved",
    caption_origin: "platform_automatic",
    caption_language: "en",
    segments: [
      {
        claim_id: "00000000-0000-0000-0000-000000000001",
        evidence_id: "00000000-0000-0000-0000-000000000002",
        start_seconds: 0,
        end_seconds: 2,
        text: "Synthetic caption cue",
      },
    ],
    omitted_segments: 0,
    subject_identity: "unknown",
    evidence_expired: false,
  };
  change(youtube);
  (view.results[0] as Record<string, unknown>).youtube = youtube;
  const api = createApi(
    "http://api",
    vi.fn().mockResolvedValue(response(view)),
  );
  await expect(api.results("j1", "w1")).rejects.toThrow("unexpected results");
});

it.each(["expired", "omitted"])(
  "accepts a retrieved caption history with no retained preview: %s",
  async (reason) => {
    const view = fitView();
    (view.results[0] as Record<string, unknown>).youtube = {
      metadata: null,
      metadata_truncated: false,
      caption_status: "retrieved",
      caption_origin: "provided",
      caption_language: "en",
      segments: [],
      omitted_segments: reason === "omitted" ? 1 : 0,
      subject_identity: "unknown",
      evidence_expired: reason === "expired",
    };
    const api = createApi(
      "http://api",
      vi.fn().mockResolvedValue(response(view)),
    );
    expect(
      (await api.results("j1", "w1")).results[0].youtube?.segments,
    ).toEqual([]);
  },
);

it.each([
  "unknown-essential",
  "missing-evidence",
  "inflated-preference",
  "invalid-comparison",
  "wrong-group",
  "duplicate-group",
])("rejects a misleading qualification payload: %s", async (variant) => {
  const view = fitView();
  const fit = view.results[0].fit;
  if (variant === "unknown-essential") fit.essential[0].outcome = "unknown";
  if (variant === "missing-evidence") fit.essential[0].evidence_ids = [];
  if (variant === "inflated-preference") fit.preference_score = 1;
  if (variant === "invalid-comparison")
    fit.essential[0].criterion.value = "25" as unknown as number;
  if (variant === "wrong-group") {
    view.groups.confirmed = [];
    view.groups.near_match = ["e1"];
  }
  if (variant === "duplicate-group") view.groups.confirmed = ["e1", "e1"];
  const api = createApi(
    "http://api",
    vi.fn().mockResolvedValue(response(view)),
  );
  await expect(api.results("j1", "w1")).rejects.toThrow("unexpected results");
});
describe("research service client", () => {
  it("submits an evidence follow-up with a scoped result ID and accepts only cited report data", async () => {
    const accepted = {
      job_id: "followup-job",
      workspace_id: "workspace",
      state: "queued",
    };
    const report = {
      job_id: "followup-job",
      source_job_id: "source-job",
      entity_id: "entity",
      state: "completed",
      status: "answered",
      coverage_complete: false,
      inference_status: "unavailable",
      expansion_status: "unavailable",
      unknowns: [],
      observations: [
        {
          evidence_id: "evidence",
          quote: "25 employees",
          source_url: "https://example.org/company",
          source_platform: "web",
          collected_at: "2026-10-14T00:00:00Z",
          excerpt_sha256: "a".repeat(64),
          qualification: "source_statement_not_independently_verified",
        },
      ],
    };
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(response(accepted, 202))
      .mockResolvedValueOnce(response(report));
    const api = createApi("http://api", fetcher, async () => "token");
    await expect(
      api.submitFollowup("source-job", "workspace", "entity", "Why fit?"),
    ).resolves.toEqual(accepted);
    await expect(
      api.followupReport("followup-job", "workspace"),
    ).resolves.toEqual(report);
    expect(fetcher.mock.calls[0][0]).toBe(
      "http://api/v1/jobs/source-job/followups?workspace_id=workspace",
    );
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({
      entity_id: "entity",
      question: "Why fit?",
    });
    expect(fetcher.mock.calls[0][1].headers.get("Authorization")).toBe(
      "Bearer token",
    );
    expect(fetcher.mock.calls[1][0]).toBe(
      "http://api/v1/jobs/followup-job/report?workspace_id=workspace",
    );
  });

  it("rejects a follow-up report with an unsafe source URL", async () => {
    const report = {
      job_id: "j",
      source_job_id: "source",
      entity_id: "entity",
      state: "completed",
      status: "answered",
      coverage_complete: false,
      inference_status: "unavailable",
      expansion_status: "unavailable",
      unknowns: [],
      observations: [
        {
          evidence_id: "e",
          quote: "A fact",
          source_url: "javascript:alert(1)",
          source_platform: "web",
          collected_at: "2026-10-14T00:00:00Z",
          excerpt_sha256: "a".repeat(64),
          qualification: "source_statement_not_independently_verified",
        },
      ],
    };
    await expect(
      createApi(
        "http://api",
        vi.fn().mockResolvedValue(response(report)),
        async () => "token",
      ).followupReport("j", "workspace"),
    ).rejects.toThrow("unexpected follow-up data");
  });

  it("starts a new scoped research run only from an explicit expansion prompt", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        response({ job_id: "next", workspace_id: "w1", state: "queued" }, 202),
      );
    const api = createApi("http://api", fetcher, async () => "token");
    await expect(
      api.expandResearch("source", "w1", " Find more companies "),
    ).resolves.toEqual({ id: "next", workspace_id: "w1", status: "queued" });
    expect(fetcher.mock.calls[0][0]).toBe(
      "http://api/v1/jobs/source/expand?workspace_id=w1",
    );
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({
      prompt: "Find more companies",
    });
  });

  it("starts an immutable refinement run from an explicit prompt", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        response(
          { job_id: "refined", workspace_id: "w1", state: "queued" },
          202,
        ),
      );
    const api = createApi("http://api", fetcher, async () => "token");
    await expect(
      api.refineResearch("source", "w1", " Exclude consultancies "),
    ).resolves.toEqual({ id: "refined", workspace_id: "w1", status: "queued" });
    expect(fetcher.mock.calls[0][0]).toBe(
      "http://api/v1/jobs/source/refine?workspace_id=w1",
    );
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({
      prompt: "Exclude consultancies",
    });
  });

  it("answers a clarification in the original workspace", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        response(
          { job_id: "planning", workspace_id: "w1", state: "queued" },
          202,
        ),
      );
    const api = createApi("http://api", fetcher, async () => "token");
    await expect(
      api.answerClarification("paused", "w1", " Company headquarters "),
    ).resolves.toEqual({
      id: "planning",
      workspace_id: "w1",
      status: "queued",
    });
    expect(fetcher.mock.calls[0][0]).toBe(
      "http://api/v1/jobs/paused/clarifications?workspace_id=w1",
    );
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({
      answer: "Company headquarters",
    });
  });

  it("creates, reads and refreshes scoped saved-list revisions", async () => {
    const id = "00000000-0000-4000-8000-000000000001";
    const list = {
      id,
      workspace_id: "w1",
      name: "Launch prospects",
      plan_id: "p1",
      created_by: "owner",
      created_at: "2026-10-14T00:00:00Z",
    };
    const frozen = {
      id,
      workspace_id: "w1",
      list_id: id,
      revision: 1,
      plan_id: "p1",
      created_at: "2026-10-14T00:00:00Z",
      created_by: "owner",
      payload: {
        snapshot_at: "2026-10-14T00:00:00Z",
        members: [],
        omitted: [],
        refresh_scope: "persisted_reviewed_facts_only",
      },
    };
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(response([list]))
      .mockResolvedValueOnce(response(list, 201))
      .mockResolvedValueOnce(response(frozen))
      .mockResolvedValueOnce(response({ ...frozen, revision: 2 }, 201));
    const api = createApi("http://api", fetcher, async () => "firebase-token");
    await expect(api.savedLists("w1")).resolves.toEqual([list]);
    await expect(
      api.createSavedList("w1", " Launch prospects ", "p1", [id]),
    ).resolves.toEqual(list);
    await expect(api.savedListSnapshot("w1", id)).resolves.toEqual(frozen);
    await expect(
      api.refreshSavedList("w1", id, [id], 1),
    ).resolves.toMatchObject({ revision: 2 });
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      "http://api/v1/workspaces/w1/lists",
      "http://api/v1/workspaces/w1/lists",
      `http://api/v1/workspaces/w1/lists/${id}/snapshots/latest`,
      `http://api/v1/workspaces/w1/lists/${id}/refresh`,
    ]);
    expect(fetcher.mock.calls[1][1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({
        name: "Launch prospects",
        plan_id: "p1",
        entity_ids: [id],
      }),
    });
    expect(fetcher.mock.calls[3][1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({ entity_ids: [id], expected_revision: 1 }),
    });
  });

  it("rejects saved-list refresh when the expected revision is stale", async () => {
    const api = createApi(
      "http://api",
      vi
        .fn()
        .mockResolvedValue(
          response({ detail: { code: "stale_snapshot_revision" } }, 409),
        ),
      async () => "token",
    );
    await expect(
      api.refreshSavedList("w1", "l1", ["e1"], 4),
    ).rejects.toMatchObject({ status: 409 });
  });

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
  it("loads only strict, scoped connection metadata for checkpoint choices", async () => {
    const metadata = [
      {
        id: "00000000-0000-4000-8000-000000000001",
        workspace_id: "w /1",
        source: "linkedin",
        auth_kind: "session",
        scopes: ["read", "discover"],
        state: "active",
        expires_at: "2099-01-01T00:00:00Z",
        access_validation: "not_performed",
        remote_revocation: "not_performed",
      },
    ];
    const fetcher = vi.fn().mockResolvedValue(response(metadata));
    await expect(
      createApi("http://api", fetcher).connections("w /1"),
    ).resolves.toEqual(metadata);
    expect(fetcher.mock.calls[0][0]).toBe(
      "http://api/v1/workspaces/w%20%2F1/connections",
    );
  });
  it("rejects secret-bearing or cross-workspace connection metadata", async () => {
    const secret = {
      id: "00000000-0000-4000-8000-000000000001",
      workspace_id: "w1",
      source: "linkedin",
      auth_kind: "session",
      scopes: ["read", "discover"],
      state: "active",
      expires_at: "2099-01-01T00:00:00Z",
      access_validation: "not_performed",
      remote_revocation: "not_performed",
      cookie: "must-not-reach-the-ui",
    };
    const wrongWorkspace = {
      ...secret,
      workspace_id: "w2",
      cookie: undefined,
    };
    await expect(
      createApi(
        "http://api",
        vi.fn().mockResolvedValue(response([secret])),
      ).connections("w1"),
    ).rejects.toThrow("unexpected connection metadata");
    await expect(
      createApi(
        "http://api",
        vi.fn().mockResolvedValue(response([wrongWorkspace])),
      ).connections("w1"),
    ).rejects.toThrow("unexpected connection metadata");
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
  it("uses same-origin health routes when production has no API URL override", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_API_URL", "");
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(response({}))
      .mockResolvedValueOnce(response({}));
    try {
      expect(await createApi(undefined, fetcher).health()).toEqual({
        live: true,
        ready: true,
      });
      expect(fetcher.mock.calls.map((call) => call[0])).toEqual([
        "/health/live",
        "/health/ready",
      ]);
    } finally {
      vi.unstubAllEnvs();
    }
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
  {
    feed: {
      feed_url: "https://example.com/feed",
      entries: [],
      duplicate_count: -1,
      invalid_link_count: 0,
      omitted_entry_count: 0,
      evidence_expired: false,
    },
  },
  {
    feed: {
      feed_url: "https://example.com/feed",
      duplicate_count: 0,
      invalid_link_count: 0,
      omitted_entry_count: 0,
      evidence_expired: false,
      entries: [
        {
          entry_id: "one",
          title: "Story",
          url: "https://example.com/one",
          summary: "Source",
          summary_truncated: false,
          published_at: "not-a-date",
          updated_at: null,
        },
      ],
    },
  },
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
  const fetcher = vi.fn().mockResolvedValue(
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

it("loads only a scoped citation and rejects a mismatched or unsafe source response", async () => {
  const citation = {
    id: "ev1",
    source_url: "https://example.org/source",
    source_platform: "web",
    excerpt: "25 employees",
    excerpt_truncated: false,
    collected_at: "2026-10-14T00:00:00Z",
    expires_at: null,
    content_hash: null,
    content_hash_status: "stored_metadata_not_revalidated",
  };
  const fetcher = vi.fn().mockResolvedValue(response(citation));
  await expect(
    createApi("http://api", fetcher).evidenceCitation("j1", "ev1", "w1"),
  ).resolves.toEqual(citation);
  expect(fetcher.mock.calls[0][0]).toBe(
    "http://api/v1/jobs/j1/evidence/ev1?workspace_id=w1",
  );
  for (const update of [
    { id: "ev2" },
    { source_url: "javascript:alert(1)" },
    { excerpt: "x".repeat(4097) },
    { content_hash_status: "verified" },
  ]) {
    const api = createApi(
      "http://api",
      vi.fn().mockResolvedValue(response({ ...citation, ...update })),
    );
    await expect(api.evidenceCitation("j1", "ev1", "w1")).rejects.toThrow(
      "unexpected source evidence",
    );
  }
});

it("loads validated scoped identity suggestions and changes them through owner actions", async () => {
  const review = {
    id: "10000000-0000-4000-8000-000000000001",
    source_id: "20000000-0000-4000-8000-000000000001",
    target_id: "30000000-0000-4000-8000-000000000001",
    state: "suggestion",
    reason: "Verified company attributes agree.",
    review_outcome: null,
  };
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(response([review]))
    .mockResolvedValueOnce(response({ ...review, state: "linked" }));
  const api = createApi("http://api", fetcher);
  await expect(api.identityReviews("w1")).resolves.toEqual([review]);
  expect(fetcher.mock.calls[0][0]).toBe(
    "http://api/v1/workspaces/w1/identity-reviews",
  );
  await expect(
    api.changeIdentityReview("w1", review.id, "approve"),
  ).resolves.toMatchObject({ id: review.id, state: "linked" });
  expect(fetcher.mock.calls[1][0]).toBe(
    `http://api/v1/workspaces/w1/identity-reviews/${review.id}/approve`,
  );
  expect(fetcher.mock.calls[1][1]).toMatchObject({ method: "POST" });

  const malformed = createApi(
    "http://api",
    vi
      .fn()
      .mockResolvedValue(response([{ ...review, source_id: "not-an-id" }])),
  );
  await expect(malformed.identityReviews("w1")).rejects.toThrow(
    "unexpected identity reviews",
  );
});

it("explains that only a workspace owner can change identity suggestions", async () => {
  const api = createApi(
    "http://api",
    vi.fn().mockResolvedValue(response({ detail: "Forbidden" }, 403)),
  );
  await expect(
    api.changeIdentityReview(
      "w1",
      "10000000-0000-4000-8000-000000000001",
      "approve",
    ),
  ).rejects.toThrow(
    "Only a workspace owner can approve or reverse identity links.",
  );
});

it("validates review proof subjects and source links before exposing owner decisions", async () => {
  const sourceId = "20000000-0000-4000-8000-000000000001";
  const targetId = "30000000-0000-4000-8000-000000000001";
  const proof = (id: string) => ({
    id,
    display_name: "Synthetic company",
    kind: "company",
    available: true,
    context_complete: true,
    identity_facts: [
      {
        claim_id: "40000000-0000-4000-8000-000000000001",
        field: "domain",
        value: "example.org",
        evidence: [
          {
            id: "50000000-0000-4000-8000-000000000001",
            source_url: "https://example.org/about",
            source_platform: "web",
            excerpt: "Official domain example.org",
            excerpt_truncated: false,
            collected_at: "2026-10-14T00:00:00Z",
            expires_at: null,
          },
        ],
      },
    ],
  });
  const detail = {
    id: "10000000-0000-4000-8000-000000000001",
    source_id: sourceId,
    target_id: targetId,
    state: "suggestion",
    reason: "corroborated_domain",
    current_reason: "corroborated_domain",
    eligible: true,
    can_review: false,
    source: proof(sourceId),
    target: proof(targetId),
  };
  const fetcher = vi.fn().mockResolvedValue(response(detail));
  await expect(
    createApi("http://api", fetcher).identityReview("w1", detail.id),
  ).resolves.toMatchObject({ can_review: false });
  expect(fetcher.mock.calls[0][0]).toBe(
    `http://api/v1/workspaces/w1/identity-reviews/${detail.id}`,
  );
  for (const invalid of [
    { ...detail, source: { ...detail.source, id: targetId } },
    {
      ...detail,
      source: {
        ...detail.source,
        identity_facts: [
          {
            ...detail.source.identity_facts[0],
            evidence: [
              {
                ...detail.source.identity_facts[0].evidence[0],
                source_url: "javascript:alert(1)",
              },
            ],
          },
        ],
      },
    },
  ]) {
    await expect(
      createApi(
        "http://api",
        vi.fn().mockResolvedValue(response(invalid)),
      ).identityReview("w1", detail.id),
    ).rejects.toThrow("unexpected identity context");
  }
});

it.each([
  ["x", "x_api_v2"],
  ["reddit", "reddit_oauth"],
])(
  "accepts direct %s citations with matching provider evidence and rejects mismatched claims",
  async (source, provider) => {
    const data = fitView();
    const candidate = data.results[0];
    candidate.source = source;
    candidate.provider = provider;
    candidate.evidence_kind = "public_post";
    const client = createApi(
      "http://api",
      vi.fn().mockImplementation(async () => response(data)),
    );
    expect((await client.results("j1", "w1")).results[0].provider).toBe(
      provider,
    );
    candidate.evidence_kind = "search_snippet";
    await expect(client.results("j1", "w1")).rejects.toThrow(
      "unexpected results",
    );
  },
);

it("loads advisory rebind choices without mutating and requires an explicit replacement request", async () => {
  const option = {
    source: "linkedin" as const,
    previous_connection_ref: "00000000-0000-4000-8000-000000000001",
    entity_ids: ["00000000-0000-4000-8000-000000000002"],
  };
  const choices = {
    job_id: "j1",
    job_version: 3,
    resume_status: "available",
    confirmation_required: true,
    options: [option],
  };
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(response(choices))
    .mockResolvedValueOnce(
      response({
        id: "j1",
        workspace_id: "w1",
        state: "queued",
        stage: "collecting",
        version: 4,
        terminal_reason: null,
      }),
    );
  const api = createApi("http://api", fetcher);
  expect((await api.rebindOptions("j1", "w1")).options).toEqual([option]);
  expect(fetcher).toHaveBeenCalledTimes(1);
  const selection = {
    ...option,
    replacement_connection_ref: "00000000-0000-4000-8000-000000000003",
    expected_job_version: 3,
  };
  await expect(
    api.rebindAndResume("j1", "w1", selection, "retained-request-key"),
  ).resolves.toMatchObject({ state: "queued" });
  const init = fetcher.mock.calls[1][1] as RequestInit;
  expect(new Headers(init.headers).get("Idempotency-Key")).toBe(
    "retained-request-key",
  );
  expect(new Headers(init.headers).get("Content-Type")).toBe(
    "application/json",
  );
  expect(JSON.parse(String(init.body))).toEqual(selection);
});

it("rejects malformed rebind choices, invalid selections and conflicting checkpoints", async () => {
  const option = {
    source: "linkedin" as const,
    previous_connection_ref: "00000000-0000-4000-8000-000000000001",
    entity_ids: ["00000000-0000-4000-8000-000000000002"],
  };
  for (const invalid of [
    {
      job_id: "another",
      job_version: 3,
      resume_status: "available",
      confirmation_required: true,
      options: [option],
    },
    {
      job_id: "j1",
      job_version: 3,
      resume_status: "deadline_expired",
      confirmation_required: true,
      options: [option],
    },
    {
      job_id: "j1",
      job_version: 3,
      resume_status: "available",
      confirmation_required: true,
      options: [option, option],
    },
  ]) {
    const api = createApi(
      "http://api",
      vi.fn().mockResolvedValue(response(invalid)),
    );
    await expect(api.rebindOptions("j1", "w1")).rejects.toThrow(
      "choices could not be verified",
    );
  }
  const fetcher = vi.fn().mockResolvedValue(response({}, 409));
  const api = createApi("http://api", fetcher);
  const selection = {
    ...option,
    replacement_connection_ref: "invalid",
    expected_job_version: 3,
  };
  await expect(
    api.rebindAndResume("j1", "w1", selection, "key"),
  ).rejects.toThrow("Choose the replacement");
  expect(fetcher).not.toHaveBeenCalled();
  selection.replacement_connection_ref = "00000000-0000-4000-8000-000000000003";
  await expect(
    api.rebindAndResume("j1", "w1", selection, "key"),
  ).rejects.toThrow("checkpoint or replacement access changed");
  for (const [status, message] of [
    [403, "initiating workspace owner"],
    [503, "Connected source collection is disabled"],
  ] as const) {
    fetcher.mockResolvedValueOnce(response({}, status));
    await expect(
      api.rebindAndResume("j1", "w1", selection, "key"),
    ).rejects.toThrow(message);
  }
  fetcher.mockResolvedValueOnce(response({}, 403));
  await expect(api.rebindOptions("j1", "w1")).rejects.toThrow(
    "initiating workspace owner",
  );
});

describe("owner role review API", () => {
  const roleRef = (suffix: string) => ({
    role_claim_id: `00000000-0000-4000-8000-00000000000${suffix}`,
    date_claim_id: `00000000-0000-4000-8000-00000000001${suffix}`,
    evidence_id: "00000000-0000-4000-8000-000000000099",
  });
  const preview = {
    entity_id: "00000000-0000-4000-8000-000000000001",
    requires_person_confirmation: true,
    requires_same_subject_confirmation: true,
    review_hash: "a".repeat(64),
    review_origin: "workspace_owner",
    subject_name: "Synthetic profile",
    previous: {
      ...roleRef("1"),
      role: "Engineer",
      effective_date: "2021-01-01",
      excerpt: "Engineer since 2021",
      source_url: "https://www.linkedin.com/in/example/",
    },
    replacement: {
      ...roleRef("2"),
      role: "Founder",
      effective_date: "2025-01-01",
      excerpt: "Founder since 2025",
      source_url: "https://www.linkedin.com/in/example/",
    },
  };
  it("binds preview to the exact candidate refs and sends separate approval confirmations", async () => {
    const fetcher = vi.fn().mockResolvedValue(response(preview));
    const api = createApi("http://api", fetcher);
    const input = {
      entity_id: preview.entity_id,
      previous: roleRef("1"),
      replacement: roleRef("2"),
    };
    await expect(
      api.previewRoleReview(
        "workspace-1",
        input,
        "https://www.linkedin.com/in/example/",
      ),
    ).resolves.toEqual(preview);
    expect(fetcher.mock.calls[0][0]).toBe(
      "http://api/v1/workspaces/workspace-1/role-refreshes/preview",
    );
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual(input);
    fetcher.mockResolvedValueOnce(
      response({
        entity_id: preview.entity_id,
        outcome: "superseded",
        review_origin: "workspace_owner",
        roles: [
          {
            claim_id: roleRef("1").role_claim_id,
            value: "Engineer",
            freshness: "historical",
            event_at: "2021-01-01T00:00:00Z",
          },
          {
            claim_id: roleRef("2").role_claim_id,
            value: "Founder",
            freshness: "current",
            event_at: "2025-01-01T00:00:00Z",
          },
        ],
      }),
    );
    await api.approveRoleReview("workspace-1", {
      ...input,
      expected_review_hash: preview.review_hash,
      same_subject_confirmed: true,
      person_subject_confirmed: true,
    });
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toMatchObject({
      same_subject_confirmed: true,
      person_subject_confirmed: true,
      expected_review_hash: preview.review_hash,
    });
    fetcher.mockResolvedValueOnce(
      response({
        entity_id: preview.entity_id,
        outcome: "superseded",
        review_origin: "workspace_owner",
        roles: [],
      }),
    );
    await expect(
      api.approveRoleReview("workspace-1", {
        ...input,
        expected_review_hash: preview.review_hash,
        same_subject_confirmed: true,
        person_subject_confirmed: true,
      }),
    ).rejects.toThrow("response was unclear");
  });
  it("rejects changed preview refs and preserves owner/conflict status", async () => {
    const altered = {
      ...preview,
      replacement: {
        ...preview.replacement,
        role_claim_id: roleRef("3").role_claim_id,
      },
    };
    const fetcher = vi.fn().mockResolvedValue(response(altered));
    const api = createApi("http://api", fetcher);
    const input = {
      entity_id: preview.entity_id,
      previous: roleRef("1"),
      replacement: roleRef("2"),
    };
    await expect(
      api.previewRoleReview(
        "workspace-1",
        input,
        "https://www.linkedin.com/in/example/",
      ),
    ).rejects.toThrow("selected evidence");
    fetcher.mockResolvedValueOnce(
      response({
        ...preview,
        previous: {
          ...preview.previous,
          source_url: "https://attacker.example/",
        },
      }),
    );
    await expect(
      api.previewRoleReview(
        "workspace-1",
        input,
        "https://www.linkedin.com/in/example/",
      ),
    ).rejects.toThrow("selected evidence");
    for (const [status, message] of [
      [403, "Only a workspace owner"],
      [409, "evidence changed"],
    ] as const) {
      fetcher.mockResolvedValueOnce(response({}, status));
      await expect(
        api.previewRoleReview(
          "workspace-1",
          input,
          "https://www.linkedin.com/in/example/",
        ),
      ).rejects.toThrow(message);
    }
  });
});

describe("safe planning failure details", () => {
  const detail = {
    reason: "invalid_interpretation",
    recovery: "revise_prompt",
    automatic_retry_allowed: false,
    source_search_started: false,
  };
  const plan = {
    job_id: "j1",
    plan_id: "p1",
    interpretation: { workspace_id: "w1" },
    status: "rejected",
    planning_failure: detail,
  };
  it("accepts the sanitized rejected-plan recovery contract", async () => {
    const api = createApi(
      "http://api",
      vi.fn().mockResolvedValue(response(plan)),
    );
    await expect(api.plan("j1", "w1")).resolves.toEqual(plan);
  });
  it.each([
    { ...detail, automatic_retry_allowed: true },
    { ...detail, source_search_started: true },
    { ...detail, recovery: "check_service" },
    { ...detail, reason: "private provider error" },
    { ...detail, raw_response: "secret" },
  ])(
    "rejects misleading or unrecognized failure metadata %#",
    async (planning_failure) => {
      const api = createApi(
        "http://api",
        vi.fn().mockResolvedValue(response({ ...plan, planning_failure })),
      );
      await expect(api.plan("j1", "w1")).rejects.toThrow(
        "unexpected planning failure",
      );
    },
  );
});

describe("connected social profile responses", () => {
  it.each(["instagram", "facebook"] as const)(
    "accepts aligned %s observations",
    async (source) => {
      const { socialCandidate } = await import("./social-fixtures");
      const payload = {
        ...fitView(),
        groups: null,
        results: [socialCandidate(source)],
      };
      const api = createApi(
        "http://api",
        vi.fn().mockResolvedValue(response(payload)),
      );
      await expect(api.results("j1", "w1")).resolves.toEqual(payload);
    },
  );
  it.each([
    "wrong_source",
    "negative_count",
    "private",
    "identity",
    "url",
    "network",
    "analytics",
  ])("rejects misleading social metadata: %s", async (issue) => {
    const { socialCandidate } = await import("./social-fixtures");
    const candidate = socialCandidate("instagram");
    const view = candidate.social_read!;
    const resource = view.resource as unknown as Record<string, unknown>;
    if (issue === "wrong_source") resource.source = "facebook";
    if (issue === "negative_count") resource.followers = -1;
    if (issue === "private") resource.visibility = "private";
    if (issue === "identity") resource.subject_identity = "person";
    if (issue === "url") resource.source_url = "https://example.com/";
    if (issue === "network") view.network_requests_seen = 0;
    if (issue === "analytics") resource.owner_analytics = "available";
    const api = createApi(
      "http://api",
      vi
        .fn()
        .mockResolvedValue(
          response({ ...fitView(), groups: null, results: [candidate] }),
        ),
    );
    await expect(api.results("j1", "w1")).rejects.toThrow();
  });
});
