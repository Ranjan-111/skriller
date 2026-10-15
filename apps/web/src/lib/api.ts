import type { components, paths } from "../generated/api";
import { decodeProgress, type ProgressUpdate } from "./progress";

export type SearchPlan = components["schemas"]["SearchPlan"];
export type Capability = components["schemas"]["Capability"];
export type ExecutionContext = components["schemas"]["ExecutionContext"];
export type ProgressEvent = components["schemas"]["ProgressEvent"];
export type SourceDiagnostic = components["schemas"]["SourceDiagnostic"];
export type PlanView = components["schemas"]["PlanView"];
export type JobUsage = components["schemas"]["JobUsage"];
export type IdentityReview = components["schemas"]["IdentityReviewView"];
export type IdentityReviewDetail =
  components["schemas"]["IdentityReviewDetail"];
export type WorkspaceAllowance = components["schemas"]["EntitlementView"];
export type Failure = components["schemas"]["Failure"];
type SnapshotEndpoint =
  paths["/v1/workspaces/{workspace_id}/jobs/{job_id}"]["get"];
type EventEndpoint =
  paths["/v1/workspaces/{workspace_id}/jobs/{job_id}/events"]["get"];
export type JobIdentity = SnapshotEndpoint["parameters"]["path"];
export type JobSnapshot =
  SnapshotEndpoint["responses"][200]["content"]["application/json"];
export type ProgressOptions = {
  lastEventId?: NonNullable<
    NonNullable<EventEndpoint["parameters"]["header"]>["last-event-id"]
  >;
  signal?: AbortSignal;
};
export type Source = NonNullable<SearchPlan["sources"]>[number];
export type YouTubeView = components["schemas"]["YouTubeView"];

export type Health = { live: boolean; ready: boolean };
export type ResearchRequest = {
  prompt: string;
  mode: "leads" | "research";
  sources: Source[];
  result_limit: number;
};
export type ResearchJob = { id: string; status: string; workspace_id?: string };
export type ResearchRun = {
  id: string;
  workspace_id: string;
  state: string;
  stage: string | null;
  version: number;
  terminal_reason: string | null;
  error_code?: string | null;
  result_count: number;
};
export type ResearchCandidate = {
  id: string;
  title: string;
  url: string;
  snippet: string;
  source: string;
  provider: "exa_keyless";
  evidence_kind: "search_snippet";
  qualification: "unverified";
  fit?: components["schemas"]["Fit"] | null;
  observed_at: string;
  provenance: components["schemas"]["QueryProvenance"][];
  collection?: components["schemas"]["CollectionView"] | null;
  extraction?: components["schemas"]["ExtractionView"] | null;
  feed?: components["schemas"]["FeedView"] | null;
  discussion?: components["schemas"]["DiscussionView"] | null;
  platform_reference?: components["schemas"]["PlatformReference"] | null;
  youtube?: YouTubeView | null;
};
export type ResearchResults = {
  job_id: string;
  workspace_id: string;
  state: string;
  results: ResearchCandidate[];
  limitations: string[];
  groups?: components["schemas"]["QualificationGroups"] | null;
};
export type SavedList = components["schemas"]["ListMetadata"];
export type SavedListSnapshot = components["schemas"]["SnapshotOutput"];
export type FollowupSubmission = components["schemas"]["FollowupSubmission"];
export type FollowupView = components["schemas"]["FollowupView"];
export function safeSourceUrl(value: string): string | null {
  try {
    const url = new URL(value);
    if (
      !["https:", "http:"].includes(url.protocol) ||
      url.username ||
      url.password
    )
      return null;
    return url.href;
  } catch {
    return null;
  }
}
export class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function validCollection(value: unknown): boolean {
  if (value == null) return true;
  if (typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  return (
    ["read", "unavailable", "preparation_failed"].includes(
      String(row.status),
    ) &&
    (row.failure_code === null || typeof row.failure_code === "string") &&
    ["observed_at", "final_url", "content_hash"].every(
      (key) => row[key] == null || typeof row[key] === "string",
    ) &&
    ["network_seconds", "parser_seconds", "browser_seconds"].every(
      (key) =>
        row[key] == null ||
        (typeof row[key] === "number" &&
          Number.isFinite(row[key]) &&
          row[key] >= 0),
    ) &&
    (row.prepared_chunks == null ||
      (typeof row.prepared_chunks === "number" &&
        Number.isInteger(row.prepared_chunks) &&
        row.prepared_chunks >= 0)) &&
    (row.coverage_complete == null ||
      typeof row.coverage_complete === "boolean")
  );
}

function validFit(value: unknown): boolean {
  if (value == null) return true;
  if (typeof value !== "object" || Array.isArray(value)) return false;
  const fit = value as Record<string, unknown>;
  const groups = ["essential", "exclusions", "preferences"] as const;
  if (
    !["confirmed", "near_match", "excluded"].includes(String(fit.status)) ||
    !Array.isArray(fit.limitations) ||
    fit.limitations.length > 64 ||
    !fit.limitations.every(
      (item: unknown) => typeof item === "string" && item.length <= 1000,
    ) ||
    !Number.isInteger(fit.preference_score) ||
    typeof fit.preference_score !== "number" ||
    fit.preference_score < 0 ||
    fit.preference_score > 20
  )
    return false;
  for (const group of groups) {
    const rows = fit[group];
    if (!Array.isArray(rows) || rows.length > 20) return false;
    for (const item of rows) {
      if (!item || typeof item !== "object" || Array.isArray(item))
        return false;
      const row = item as Record<string, unknown>;
      if (
        !["matched", "contradicted", "unknown"].includes(String(row.outcome)) ||
        typeof row.reason !== "string" ||
        row.reason.length > 500 ||
        !Array.isArray(row.evidence_ids) ||
        row.evidence_ids.length > 10 ||
        (row.outcome !== "unknown" && row.evidence_ids.length === 0) ||
        !row.evidence_ids.every(
          (id: unknown) =>
            typeof id === "string" &&
            /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
              id,
            ),
        ) ||
        !row.criterion ||
        typeof row.criterion !== "object" ||
        Array.isArray(row.criterion)
      )
        return false;
      const criterion = row.criterion as Record<string, unknown>;
      const scalar = criterion.value;
      if (
        typeof criterion.field !== "string" ||
        !/^[a-z][a-z0-9_]{0,79}$/.test(criterion.field) ||
        !["eq", "gte", "lte", "contains", "in", "recent"].includes(
          String(criterion.operator),
        ) ||
        !(
          typeof scalar === "boolean" ||
          (typeof scalar === "number" && Number.isFinite(scalar)) ||
          (typeof scalar === "string" && scalar.length <= 500) ||
          (Array.isArray(scalar) &&
            scalar.length <= 20 &&
            scalar.every(
              (part: unknown) => typeof part === "string" && part.length <= 100,
            ))
        )
      )
        return false;
      if (
        (["gte", "lte", "recent"].includes(String(criterion.operator)) &&
          (typeof scalar !== "number" ||
            (criterion.operator === "recent" && scalar < 0))) ||
        (criterion.operator === "contains" && typeof scalar !== "string") ||
        (criterion.operator === "in" && !Array.isArray(scalar)) ||
        (criterion.operator === "eq" && Array.isArray(scalar))
      )
        return false;
    }
  }
  const essential = fit.essential as { outcome: string }[];
  const exclusions = fit.exclusions as { outcome: string }[];
  const preferences = fit.preferences as { outcome: string }[];
  return (
    fit.preference_score ===
      preferences.filter((row) => row.outcome === "matched").length &&
    (fit.status !== "confirmed" ||
      (essential.length > 0 &&
        essential.every((row) => row.outcome === "matched") &&
        exclusions.every((row) => row.outcome === "contradicted") &&
        fit.limitations.length === 0))
  );
}

function validGroups(value: unknown, candidates: unknown[]): boolean {
  if (value == null) return true;
  if (typeof value !== "object" || Array.isArray(value)) return false;
  const groups = value as Record<string, unknown>;
  const byId = new Map(
    candidates.map((candidate) => {
      const row = candidate as Record<string, unknown>;
      return [
        row.id,
        (row.fit as Record<string, unknown> | undefined)?.status ??
          "unverified",
      ];
    }),
  );
  const seen = new Set<string>();
  for (const status of ["confirmed", "near_match", "excluded", "unverified"]) {
    const ids = groups[status];
    if (!Array.isArray(ids) || ids.length > 100) return false;
    for (const id of ids) {
      if (typeof id !== "string" || seen.has(id) || byId.get(id) !== status)
        return false;
      seen.add(id);
    }
  }
  return seen.size === candidates.length;
}

function validExtraction(value: unknown): boolean {
  if (value == null) return true;
  if (typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  return (
    ["observed", "unavailable"].includes(String(row.status)) &&
    (row.failure_code === null || typeof row.failure_code === "string") &&
    ["rejected_claims", "omitted_chunks"].every(
      (key) =>
        typeof row[key] === "number" &&
        Number.isInteger(row[key]) &&
        row[key] >= 0,
    ) &&
    typeof row.coverage_complete === "boolean" &&
    (row.expired_observations == null ||
      (typeof row.expired_observations === "number" &&
        Number.isInteger(row.expired_observations) &&
        row.expired_observations >= 0)) &&
    Array.isArray(row.observations) &&
    row.observations.length <= 60 &&
    row.observations.every((value) => {
      if (!value || typeof value !== "object") return false;
      const fact = value as Record<string, unknown>;
      return (
        typeof fact.claim_id === "string" &&
        typeof fact.field === "string" &&
        fact.field.length <= 40 &&
        typeof fact.quote === "string" &&
        fact.quote.length > 0 &&
        fact.quote.length <= 4096 &&
        ["unverified", "conflict", "accepted"].includes(String(fact.status)) &&
        (fact.evidence_ids == null ||
          (Array.isArray(fact.evidence_ids) &&
            fact.evidence_ids.length <= 10 &&
            fact.evidence_ids.every(
              (id: unknown) =>
                typeof id === "string" && /^[0-9a-f-]{36}$/i.test(id),
            ))) &&
        ((typeof fact.value === "string" && fact.value.length <= 4096) ||
          typeof fact.value === "boolean" ||
          (typeof fact.value === "number" && Number.isFinite(fact.value)))
      );
    })
  );
}

function validFeed(value: unknown): boolean {
  if (value == null) return true;
  if (typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  return (
    typeof row.feed_url === "string" &&
    row.feed_url.length <= 4096 &&
    typeof row.evidence_expired === "boolean" &&
    ["duplicate_count", "invalid_link_count", "omitted_entry_count"].every(
      (key) =>
        typeof row[key] === "number" &&
        Number.isInteger(row[key]) &&
        row[key] >= 0,
    ) &&
    Array.isArray(row.entries) &&
    row.entries.length <= 20 &&
    row.entries.every((value) => {
      if (!value || typeof value !== "object") return false;
      const entry = value as Record<string, unknown>;
      return (
        typeof entry.entry_id === "string" &&
        entry.entry_id.length <= 4096 &&
        typeof entry.title === "string" &&
        entry.title.length <= 1000 &&
        typeof entry.url === "string" &&
        entry.url.length <= 4096 &&
        typeof entry.summary === "string" &&
        entry.summary.length <= 4096 &&
        typeof entry.summary_truncated === "boolean" &&
        ["published_at", "updated_at"].every(
          (key) =>
            entry[key] === null ||
            (typeof entry[key] === "string" &&
              Number.isFinite(Date.parse(entry[key]))),
        )
      );
    })
  );
}

function validYouTube(value: unknown): value is YouTubeView {
  if (value == null) return true;
  if (typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  const validCount = (item: unknown) =>
    item === null ||
    (typeof item === "number" && Number.isSafeInteger(item) && item >= 0);
  const validMetadata = (item: unknown) => {
    if (item === null) return true;
    if (!item || typeof item !== "object" || Array.isArray(item)) return false;
    const metadata = item as Record<string, unknown>;
    const source =
      typeof metadata.source_url === "string"
        ? safeSourceUrl(metadata.source_url)
        : null;
    let youtubeHost = false;
    try {
      const hostname = new URL(source ?? "").hostname.toLowerCase();
      youtubeHost =
        hostname === "youtube.com" ||
        hostname.endsWith(".youtube.com") ||
        hostname === "youtu.be";
    } catch {
      youtubeHost = false;
    }
    return (
      metadata.source === "youtube" &&
      metadata.evidence_kind === "public_video_metadata" &&
      metadata.counter_scope === "public_metadata" &&
      typeof metadata.title === "string" &&
      metadata.title.length <= 500 &&
      (metadata.channel === null ||
        metadata.channel === undefined ||
        (typeof metadata.channel === "string" &&
          metadata.channel.length <= 300)) &&
      (metadata.channel_url === null ||
        metadata.channel_url === undefined ||
        (typeof metadata.channel_url === "string" &&
          metadata.channel_url.length <= 4096 &&
          Boolean(safeSourceUrl(metadata.channel_url)))) &&
      (metadata.description === null ||
        metadata.description === undefined ||
        (typeof metadata.description === "string" &&
          metadata.description.length <= 8192)) &&
      (metadata.duration_seconds === null ||
        metadata.duration_seconds === undefined ||
        (typeof metadata.duration_seconds === "number" &&
          Number.isFinite(metadata.duration_seconds) &&
          metadata.duration_seconds >= 0)) &&
      (metadata.view_count === undefined || validCount(metadata.view_count)) &&
      (metadata.like_count === undefined || validCount(metadata.like_count)) &&
      typeof metadata.observed_at === "string" &&
      Number.isFinite(Date.parse(metadata.observed_at)) &&
      (metadata.published_on === null ||
        metadata.published_on === undefined ||
        (typeof metadata.published_on === "string" &&
          /^\d{4}-\d{2}-\d{2}$/.test(metadata.published_on) &&
          Number.isFinite(Date.parse(`${metadata.published_on}T00:00:00Z`)))) &&
      youtubeHost &&
      Array.isArray(metadata.transcript_languages) &&
      metadata.transcript_languages.length <= 50 &&
      metadata.transcript_languages.every(
        (language: unknown) =>
          typeof language === "string" &&
          language.length > 0 &&
          language.length <= 30,
      ) &&
      ["available", "unavailable"].includes(String(metadata.transcript_state))
    );
  };
  if (
    typeof row.metadata_truncated !== "boolean" ||
    ![
      "retrieved",
      "unavailable",
      "unsupported_format_or_language",
      "read_failed",
    ].includes(String(row.caption_status)) ||
    !(
      row.caption_origin === null ||
      ["provided", "platform_automatic"].includes(String(row.caption_origin))
    ) ||
    !(
      row.caption_language === null ||
      ["en", "en-orig", "en-US", "en-GB"].includes(String(row.caption_language))
    ) ||
    typeof row.evidence_expired !== "boolean" ||
    row.subject_identity !== "unknown" ||
    !Number.isSafeInteger(row.omitted_segments) ||
    (row.omitted_segments as number) < 0 ||
    !validMetadata(row.metadata) ||
    !Array.isArray(row.segments) ||
    row.segments.length > 20
  )
    return false;
  if (row.caption_status === "retrieved") {
    if (
      row.caption_origin === null ||
      row.caption_language === null ||
      (row.segments.length === 0 &&
        row.evidence_expired !== true &&
        row.omitted_segments === 0)
    )
      return false;
  } else if (
    row.caption_origin !== null ||
    row.caption_language !== null ||
    row.segments.length > 0
  ) {
    return false;
  }
  return row.segments.every((item: unknown) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return false;
    const segment = item as Record<string, unknown>;
    return (
      typeof segment.claim_id === "string" &&
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
        segment.claim_id,
      ) &&
      typeof segment.evidence_id === "string" &&
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
        segment.evidence_id,
      ) &&
      typeof segment.start_seconds === "number" &&
      Number.isFinite(segment.start_seconds) &&
      segment.start_seconds >= 0 &&
      typeof segment.end_seconds === "number" &&
      Number.isFinite(segment.end_seconds) &&
      segment.end_seconds > segment.start_seconds &&
      typeof segment.text === "string" &&
      segment.text.length > 0 &&
      segment.text.length <= 4000
    );
  });
}

function validAllowance(
  value: unknown,
  workspaceId?: string,
): value is WorkspaceAllowance {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  return (
    typeof row.workspace_id === "string" &&
    (!workspaceId || row.workspace_id === workspaceId) &&
    ["trial", "pilot"].includes(String(row.tier)) &&
    typeof row.enabled === "boolean" &&
    typeof row.can_manage === "boolean" &&
    [
      "run_limit",
      "result_cap",
      "source_cap",
      "result_limit",
      "source_limit",
      "used_runs",
      "remaining_runs",
    ].every(
      (key) =>
        typeof row[key] === "number" &&
        Number.isInteger(row[key]) &&
        row[key] >= 0,
    ) &&
    Number(row.run_limit) <= 1000 &&
    Number(row.result_cap) >= 1 &&
    Number(row.result_cap) <= 100 &&
    Number(row.source_cap) >= 1 &&
    Number(row.source_cap) <= 9 &&
    Number(row.result_limit) >= 1 &&
    Number(row.result_limit) <= Number(row.result_cap) &&
    Number(row.source_limit) >= 1 &&
    Number(row.source_limit) <= Number(row.source_cap) &&
    row.remaining_runs ===
      Math.max(0, Number(row.run_limit) - Number(row.used_runs))
  );
}

export function createApi(
  baseUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
  fetcher: typeof fetch = fetch,
  getToken?: (forceRefresh?: boolean) => Promise<string | null>,
) {
  async function request(
    path: string,
    init: RequestInit = {},
    authenticated = false,
  ) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    try {
      const headers = new Headers(init.headers);
      if (authenticated && getToken) {
        try {
          const token = await getToken();
          if (!token) throw new Error("No app session");
          headers.set("Authorization", `Bearer ${token}`);
        } catch {
          throw new ApiError(
            "Sign in again to your app account. Your prompt is kept here.",
            401,
          );
        }
      }
      const fetchRequest = () =>
        fetcher(`${baseUrl.replace(/\/$/, "")}${path}`, {
          ...init,
          headers,
          signal: init.signal
            ? AbortSignal.any([controller.signal, init.signal])
            : controller.signal,
          cache: "no-store",
        });
      const response = await fetchRequest();
      if (authenticated && getToken && response.status === 401) {
        try {
          const token = await getToken(true);
          if (!token) throw new Error("No app session");
          headers.set("Authorization", `Bearer ${token}`);
        } catch {
          throw new ApiError(
            "Sign in again to your app account. Your prompt is kept here.",
            401,
          );
        }
        return await fetchRequest();
      }
      return response;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (init.signal?.aborted) throw error;
      if (error instanceof Error && error.name === "AbortError")
        throw new ApiError("The service took too long to respond. Try again.");
      throw new ApiError(
        "Cannot reach the research service. Check that it is running, then try again.",
      );
    } finally {
      clearTimeout(timer);
    }
  }
  async function jsonRequest(
    path: string,
    init: RequestInit = {},
  ): Promise<unknown> {
    const response = await request(path, init, true);
    requireSuccess(response);
    try {
      return await response.json();
    } catch {
      throw new ApiError(
        "The service returned an unexpected response. No run has been confirmed.",
      );
    }
  }
  function requireSuccess(response: Response) {
    if (
      response.status === 422 &&
      response.headers.get("X-Skriller-Failure") === "entitlement_limits"
    )
      throw new ApiError(
        "The requested result or source count exceeds workspace limits. Adjust the options or ask the owner to review settings. Your prompt is kept here.",
        response.status,
      );
    if ([404, 501, 503].includes(response.status))
      throw new ApiError(
        "Research execution is not available yet. Your prompt is kept here; try again after the job service is enabled.",
        response.status,
      );
    if (response.status === 401 || response.status === 403)
      throw new ApiError(
        "Sign in again to your app account before starting research. Your prompt is kept here.",
        response.status,
      );
    if (!response.ok)
      throw new ApiError(
        response.status === 429
          ? "The workspace has reached its run limit. Ask the owner to review the pilot allowance. Your prompt is kept here."
          : "The research request could not be started. Your prompt is kept here; try again.",
        response.status,
      );
  }
  const client = {
    async allowance(): Promise<WorkspaceAllowance> {
      const data = await jsonRequest("/v1/workspace/entitlements");
      if (!validAllowance(data))
        throw new ApiError(
          "The service returned an unexpected workspace allowance.",
        );
      return data;
    },
    async updateAllowance(
      workspaceId: string,
      settings: {
        enabled: boolean;
        result_limit: number;
        source_limit: number;
      },
    ): Promise<WorkspaceAllowance> {
      let data: unknown;
      try {
        data = await jsonRequest(
          `/v1/workspaces/${encodeURIComponent(workspaceId)}/entitlements`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(settings),
          },
        );
      } catch (error) {
        if (error instanceof ApiError && error.status === 403)
          throw new ApiError(
            "Only the workspace owner can change these settings.",
            403,
          );
        throw error;
      }
      if (!validAllowance(data, workspaceId))
        throw new ApiError(
          "The service returned an unexpected workspace allowance.",
        );
      return data;
    },
    async health(): Promise<Health> {
      const [live, ready] = await Promise.all([
        request("/health/live"),
        request("/health/ready"),
      ]);
      return { live: live.ok, ready: ready.ok };
    },
    async submit(input: ResearchRequest): Promise<ResearchJob> {
      const conversation = await jsonRequest("/v1/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (
        !conversation ||
        typeof conversation !== "object" ||
        !("id" in conversation) ||
        typeof conversation.id !== "string" ||
        !conversation.id
      )
        throw new ApiError(
          "The service returned an unexpected conversation response. No run has been confirmed.",
        );
      const message = await jsonRequest(
        `/v1/conversations/${encodeURIComponent(conversation.id)}/messages`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            content: input.prompt,
            options: {
              mode: input.mode,
              sources: input.sources,
              result_limit: input.result_limit,
            },
          }),
        },
      );
      if (!message || typeof message !== "object")
        throw new ApiError(
          "The service returned an unexpected response. No run has been confirmed.",
        );
      if (
        "clarification" in message &&
        typeof message.clarification === "string" &&
        message.clarification
      )
        throw new ApiError(message.clarification);
      if (
        !("job_id" in message) ||
        typeof message.job_id !== "string" ||
        !message.job_id
      )
        throw new ApiError(
          "The service returned an unexpected response. No run has been confirmed.",
        );
      return {
        id: message.job_id,
        status: "accepted",
        ...("workspace_id" in message &&
        typeof message.workspace_id === "string"
          ? { workspace_id: message.workspace_id }
          : {}),
      };
    },
    snapshot(identity: JobIdentity): Promise<JobSnapshot> {
      return jsonRequest(
        `/v1/workspaces/${encodeURIComponent(identity.workspace_id)}/jobs/${encodeURIComponent(identity.job_id)}`,
      ) as Promise<JobSnapshot>;
    },
    async progress(
      identity: JobIdentity,
      options: ProgressOptions = {},
    ): Promise<Response> {
      const headers = new Headers({ Accept: "text/event-stream" });
      if (options.lastEventId !== undefined) {
        if (
          !/^[0-9]+$/.test(options.lastEventId) ||
          BigInt(options.lastEventId) > 2n ** 63n - 1n
        )
          throw new ApiError("Invalid progress cursor.");
        headers.set("Last-Event-ID", options.lastEventId);
      }
      const response = await request(
        `/v1/workspaces/${encodeURIComponent(identity.workspace_id)}/jobs/${encodeURIComponent(identity.job_id)}/events`,
        { headers, signal: options.signal },
        true,
      );
      requireSuccess(response);
      if (
        response.headers
          .get("Content-Type")
          ?.split(";")[0]
          .trim()
          .toLowerCase() !== "text/event-stream"
      )
        throw new ApiError(
          "The service returned an unexpected progress stream.",
        );
      return response;
    },
    async *progressEvents(
      identity: JobIdentity,
      options: ProgressOptions = {},
    ): AsyncGenerator<ProgressUpdate> {
      const response = await client.progress(identity, options);
      yield* decodeProgress(response);
    },
    async job(
      id: string,
      workspaceId?: string,
      signal?: AbortSignal,
    ): Promise<ResearchRun> {
      const query = workspaceId
        ? `?workspace_id=${encodeURIComponent(workspaceId)}`
        : "";
      const data = await jsonRequest(
        `/v1/jobs/${encodeURIComponent(id)}${query}`,
        { signal },
      );
      if (
        !data ||
        typeof data !== "object" ||
        !("id" in data) ||
        data.id !== id ||
        !("workspace_id" in data) ||
        typeof data.workspace_id !== "string" ||
        (workspaceId && data.workspace_id !== workspaceId) ||
        !("state" in data) ||
        typeof data.state !== "string" ||
        !("stage" in data) ||
        (data.stage !== null && typeof data.stage !== "string") ||
        !("version" in data) ||
        !Number.isSafeInteger(data.version) ||
        !("terminal_reason" in data) ||
        (data.terminal_reason !== null &&
          typeof data.terminal_reason !== "string") ||
        !("result_count" in data) ||
        !Number.isSafeInteger(data.result_count)
      )
        throw new ApiError(
          "The service returned an unexpected run response. Try checking the run again.",
        );
      return data as ResearchRun;
    },
    async cancel(id: string, workspaceId?: string): Promise<void> {
      const query = workspaceId
        ? `?workspace_id=${encodeURIComponent(workspaceId)}`
        : "";
      const data = await jsonRequest(
        `/v1/jobs/${encodeURIComponent(id)}/cancel${query}`,
        { method: "POST" },
      );
      if (
        !data ||
        typeof data !== "object" ||
        !("id" in data) ||
        data.id !== id ||
        !("workspace_id" in data) ||
        typeof data.workspace_id !== "string" ||
        (workspaceId && data.workspace_id !== workspaceId) ||
        !("state" in data) ||
        typeof data.state !== "string" ||
        !["cancelled", "completed", "partial", "failed"].includes(data.state)
      ) {
        throw new ApiError(
          "Cancellation was not confirmed. Check the run again.",
        );
      }
    },
    async resume(id: string, workspaceId: string): Promise<void> {
      const query = `?workspace_id=${encodeURIComponent(workspaceId)}`;
      const response = await request(
        `/v1/jobs/${encodeURIComponent(id)}/resume${query}`,
        {
          method: "POST",
          headers: { "Idempotency-Key": globalThis.crypto.randomUUID() },
        },
        true,
      );
      if (response.status === 409)
        throw new ApiError(
          "This run cannot safely resume. Its checkpoint or budget needs attention; your saved results are still available.",
          409,
        );
      requireSuccess(response);
      let data: unknown;
      try {
        data = await response.json();
      } catch {
        throw new ApiError("The service did not confirm that the run resumed.");
      }
      if (
        !data ||
        typeof data !== "object" ||
        !("id" in data) ||
        data.id !== id ||
        !("workspace_id" in data) ||
        data.workspace_id !== workspaceId ||
        !("state" in data) ||
        data.state !== "queued"
      )
        throw new ApiError("The service did not confirm that the run resumed.");
    },
    async answerClarification(
      id: string,
      workspaceId: string,
      answer: string,
      signal?: AbortSignal,
    ): Promise<ResearchJob> {
      const cleaned = answer.trim();
      if (cleaned.length < 1 || new TextEncoder().encode(cleaned).length > 500)
        throw new ApiError(
          "Enter a clarification answer of at most 500 bytes.",
        );
      const response = await request(
        `/v1/jobs/${encodeURIComponent(id)}/clarifications?workspace_id=${encodeURIComponent(workspaceId)}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": globalThis.crypto.randomUUID(),
          },
          body: JSON.stringify({ answer: cleaned }),
          signal,
        },
        true,
      );
      requireSuccess(response);
      const data = (await response.json()) as Record<string, unknown>;
      if (
        typeof data.job_id !== "string" ||
        data.workspace_id !== workspaceId ||
        !["queued", "running", "completed", "paused"].includes(
          String(data.state),
        )
      )
        throw new ApiError(
          "The service did not confirm the clarification run.",
        );
      return {
        id: data.job_id,
        workspace_id: workspaceId,
        status: String(data.state),
      };
    },
    async sourceDiagnostics(
      workspaceId: string,
      signal?: AbortSignal,
    ): Promise<SourceDiagnostic[]> {
      const data = await jsonRequest(
        `/v1/workspaces/${encodeURIComponent(workspaceId)}/sources`,
        { signal },
      );
      if (
        !Array.isArray(data) ||
        data.length > 27 ||
        !data.every((item: unknown) => {
          if (!item || typeof item !== "object") return false;
          const diagnostic = item as Record<string, unknown>;
          if (
            typeof diagnostic.disabled !== "boolean" ||
            diagnostic.credential_validation !== "not_performed" ||
            !["public_indexed_references", "dedicated_adapter"].includes(
              String(diagnostic.evidence_scope),
            ) ||
            ![
              "disabled",
              "unavailable",
              "needs_connection",
              "experimental",
              "ready",
              "diagnostic_error",
              "needs_access_agreement",
              "rate_limited",
            ].includes(String(diagnostic.setup_state)) ||
            !diagnostic.capability ||
            typeof diagnostic.capability !== "object"
          )
            return false;
          const capability = diagnostic.capability as Record<string, unknown>;
          return (
            typeof capability.source === "string" &&
            typeof capability.operation === "string" &&
            typeof capability.access_route === "string" &&
            capability.access_route.length <= 1000
          );
        })
      )
        throw new ApiError(
          "The service returned unexpected source readiness data.",
        );
      return data as SourceDiagnostic[];
    },
    async plan(
      id: string,
      workspaceId: string,
      signal?: AbortSignal,
    ): Promise<PlanView> {
      const data = await jsonRequest(
        `/v1/jobs/${encodeURIComponent(id)}/plan?workspace_id=${encodeURIComponent(workspaceId)}`,
        { signal },
      );
      if (
        !data ||
        typeof data !== "object" ||
        !("job_id" in data) ||
        data.job_id !== id ||
        !("interpretation" in data) ||
        !data.interpretation ||
        typeof data.interpretation !== "object" ||
        !("status" in data) ||
        typeof data.status !== "string"
      )
        throw new ApiError("The service returned unexpected plan details.");
      return data as PlanView;
    },
    async usage(
      id: string,
      workspaceId: string,
      signal?: AbortSignal,
    ): Promise<JobUsage> {
      const data = await jsonRequest(
        `/v1/jobs/${encodeURIComponent(id)}/usage?workspace_id=${encodeURIComponent(workspaceId)}`,
        { signal },
      );
      const moneyFields = [
        "budget_cap_usd",
        "confirmed_cost_usd",
        "estimated_cost_usd",
        "reserved_cost_usd",
        "exposure_ceiling_usd",
        "remaining_budget_usd",
      ];
      const usageRecord = data as Record<string, unknown> | null;
      if (
        !data ||
        typeof data !== "object" ||
        !("job_id" in data) ||
        data.job_id !== id ||
        !("workspace_id" in data) ||
        data.workspace_id !== workspaceId ||
        !("currency" in data) ||
        data.currency !== "USD" ||
        !moneyFields.every(
          (field) =>
            field in (usageRecord ?? {}) &&
            typeof usageRecord?.[field] === "string" &&
            /^(?:0|[1-9]\d*)(?:\.\d{1,8})?$/.test(usageRecord[field] as string),
        ) ||
        !("dimensions" in data) ||
        !data.dimensions ||
        typeof data.dimensions !== "object" ||
        !("stage_metrics" in data) ||
        !Array.isArray(data.stage_metrics) ||
        data.stage_metrics.length > 100 ||
        !("invalid_stage_observations" in data) ||
        typeof data.invalid_stage_observations !== "number" ||
        !("stage_metrics_truncated" in data) ||
        typeof data.stage_metrics_truncated !== "boolean" ||
        !data.stage_metrics.every((item: unknown) => {
          if (!item || typeof item !== "object") return false;
          const metric = item as Record<string, unknown>;
          return (
            typeof metric.stage === "string" &&
            typeof metric.source === "string" &&
            [
              "observations",
              "succeeded",
              "failed",
              "accepted_result_count",
              "unpriced_observations",
              "correlated_attempt_observations",
              "queue_wait_samples",
            ].every(
              (field) =>
                typeof metric[field] === "number" &&
                Number.isInteger(metric[field]) &&
                metric[field] >= 0,
            ) &&
            typeof metric.outcomes === "object" &&
            metric.outcomes !== null &&
            Object.entries(metric.outcomes).every(
              ([outcome, count]) =>
                /^[a-z][a-z0-9_]{0,49}$/.test(outcome) &&
                typeof count === "number" &&
                Number.isInteger(count) &&
                count >= 0 &&
                count <= (metric.observations as number),
            ) &&
            Object.values(metric.outcomes).reduce(
              (total, count) => total + (typeof count === "number" ? count : 0),
              0,
            ) <= (metric.observations as number) &&
            typeof metric.correlated_attempt_observations === "number" &&
            Number.isInteger(metric.correlated_attempt_observations) &&
            metric.correlated_attempt_observations >= 0 &&
            metric.correlated_attempt_observations <=
              (metric.observations as number) &&
            typeof metric.queue_wait_samples === "number" &&
            Number.isInteger(metric.queue_wait_samples) &&
            metric.queue_wait_samples >= 0 &&
            metric.queue_wait_samples <= (metric.observations as number) &&
            (metric.collection_timings === null ||
              (typeof metric.collection_timings === "object" &&
                metric.collection_timings !== null &&
                Number.isInteger(
                  (metric.collection_timings as Record<string, unknown>)
                    .observations,
                ) &&
                ((metric.collection_timings as Record<string, number>)
                  .observations ?? -1) >= 0 &&
                ((metric.collection_timings as Record<string, number>)
                  .observations ?? Infinity) <=
                  (metric.observations as number) &&
                (["network", "parser", "browser"] as const).every(
                  (component) => {
                    const timings = metric.collection_timings as Record<
                      string,
                      unknown
                    >;
                    const seconds = timings[`${component}_seconds`];
                    const samples = timings[`${component}_samples`];
                    return (
                      Number.isInteger(samples) &&
                      (samples as number) >= 0 &&
                      (samples as number) <= (timings.observations as number) &&
                      ((samples === 0 && seconds === null) ||
                        (typeof seconds === "string" &&
                          /^(?:0|[1-9]\\d*)(?:\\.\\d{1,8})?$/.test(seconds) &&
                          Number(seconds) <= 180 * (samples as number)))
                    );
                  },
                ))) &&
            [
              "stage_io_seconds",
              "confirmed_cost_usd",
              "estimated_cost_usd",
              "queue_wait_seconds",
            ].every(
              (field) =>
                typeof metric[field] === "string" &&
                /^(?:0|[1-9]\d*)(?:\.\d{1,8})?$/.test(metric[field] as string),
            )
          );
        })
      )
        throw new ApiError(
          "The service returned unexpected run usage details.",
        );
      return data as JobUsage;
    },
    async evidenceCitation(
      jobId: string,
      evidenceId: string,
      workspaceId: string,
      signal?: AbortSignal,
    ): Promise<components["schemas"]["EvidenceCitation"]> {
      const data = await jsonRequest(
        `/v1/jobs/${encodeURIComponent(jobId)}/evidence/${encodeURIComponent(evidenceId)}?workspace_id=${encodeURIComponent(workspaceId)}`,
        { signal },
      );
      if (!data || typeof data !== "object" || Array.isArray(data))
        throw new ApiError("The service returned unexpected source evidence.");
      const row = data as Record<string, unknown>;
      if (
        row.id !== evidenceId ||
        typeof row.source_url !== "string" ||
        row.source_url.length > 4096 ||
        !safeSourceUrl(row.source_url) ||
        !["web", "github", "rss", "youtube"].includes(
          String(row.source_platform),
        ) ||
        typeof row.excerpt !== "string" ||
        !row.excerpt ||
        row.excerpt.length > 4096 ||
        typeof row.excerpt_truncated !== "boolean" ||
        typeof row.collected_at !== "string" ||
        !Number.isFinite(Date.parse(row.collected_at)) ||
        (row.expires_at !== null &&
          (typeof row.expires_at !== "string" ||
            !Number.isFinite(Date.parse(row.expires_at)))) ||
        (row.content_hash !== null &&
          (typeof row.content_hash !== "string" ||
            !/^[0-9a-f]{64}$/.test(row.content_hash))) ||
        row.content_hash_status !== "stored_metadata_not_revalidated"
      )
        throw new ApiError("The service returned unexpected source evidence.");
      return data as components["schemas"]["EvidenceCitation"];
    },
    async identityReviews(
      workspaceId: string,
      signal?: AbortSignal,
    ): Promise<IdentityReview[]> {
      const data = await jsonRequest(
        `/v1/workspaces/${encodeURIComponent(workspaceId)}/identity-reviews`,
        { signal },
      );
      if (
        !Array.isArray(data) ||
        data.length > 100 ||
        !data.every((value: unknown) => {
          if (!value || typeof value !== "object" || Array.isArray(value))
            return false;
          const row = value as Record<string, unknown>;
          return (
            typeof row.id === "string" &&
            typeof row.source_id === "string" &&
            typeof row.target_id === "string" &&
            [row.id, row.source_id, row.target_id].every((id) =>
              /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
                String(id),
              ),
            ) &&
            ["suggestion", "linked", "reversed"].includes(String(row.state)) &&
            typeof row.reason === "string" &&
            row.reason.length <= 1000 &&
            (row.review_outcome == null ||
              (typeof row.review_outcome === "string" &&
                row.review_outcome.length <= 1000))
          );
        })
      )
        throw new ApiError("The service returned unexpected identity reviews.");
      return data as IdentityReview[];
    },
    async changeIdentityReview(
      workspaceId: string,
      reviewId: string,
      action: "approve" | "reverse",
      signal?: AbortSignal,
    ): Promise<IdentityReview> {
      let data: unknown;
      try {
        data = await jsonRequest(
          `/v1/workspaces/${encodeURIComponent(workspaceId)}/identity-reviews/${encodeURIComponent(reviewId)}/${action}`,
          { method: "POST", signal },
        );
      } catch (failure) {
        if (failure instanceof ApiError && failure.status === 403)
          throw new ApiError(
            "Only a workspace owner can approve or reverse identity links.",
            403,
          );
        throw failure;
      }
      if (!data || typeof data !== "object" || Array.isArray(data))
        throw new ApiError("The service did not confirm the identity review.");
      const row = data as Record<string, unknown>;
      if (
        row.id !== reviewId ||
        !["suggestion", "linked", "reversed"].includes(String(row.state)) ||
        typeof row.reason !== "string"
      )
        throw new ApiError("The service did not confirm the identity review.");
      return data as IdentityReview;
    },
    async identityReview(
      workspaceId: string,
      reviewId: string,
      signal?: AbortSignal,
    ): Promise<IdentityReviewDetail> {
      const data = await jsonRequest(
        `/v1/workspaces/${encodeURIComponent(workspaceId)}/identity-reviews/${encodeURIComponent(reviewId)}`,
        { signal },
      );
      const uuid = (value: unknown) =>
        typeof value === "string" &&
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
          value,
        );
      const subject = (value: unknown, expected: unknown) => {
        if (!value || typeof value !== "object" || Array.isArray(value))
          return false;
        const row = value as Record<string, unknown>;
        return (
          row.id === expected &&
          uuid(row.id) &&
          typeof row.display_name === "string" &&
          row.display_name.length <= 200 &&
          typeof row.kind === "string" &&
          typeof row.available === "boolean" &&
          typeof row.context_complete === "boolean" &&
          Array.isArray(row.identity_facts) &&
          row.identity_facts.length <= 20 &&
          row.identity_facts.every((fact: unknown) => {
            if (!fact || typeof fact !== "object" || Array.isArray(fact))
              return false;
            const item = fact as Record<string, unknown>;
            return (
              uuid(item.claim_id) &&
              typeof item.field === "string" &&
              typeof item.value === "string" &&
              item.value.length <= 255 &&
              Array.isArray(item.evidence) &&
              item.evidence.length > 0 &&
              item.evidence.length <= 10 &&
              item.evidence.every((citation: unknown) => {
                if (
                  !citation ||
                  typeof citation !== "object" ||
                  Array.isArray(citation)
                )
                  return false;
                const ev = citation as Record<string, unknown>;
                return (
                  uuid(ev.id) &&
                  typeof ev.source_url === "string" &&
                  Boolean(safeSourceUrl(ev.source_url)) &&
                  ["web", "github", "rss", "youtube"].includes(
                    String(ev.source_platform),
                  ) &&
                  typeof ev.excerpt === "string" &&
                  ev.excerpt.length > 0 &&
                  ev.excerpt.length <= 4096 &&
                  typeof ev.excerpt_truncated === "boolean" &&
                  typeof ev.collected_at === "string" &&
                  Number.isFinite(Date.parse(ev.collected_at)) &&
                  (ev.expires_at === null ||
                    (typeof ev.expires_at === "string" &&
                      Number.isFinite(Date.parse(ev.expires_at))))
                );
              })
            );
          })
        );
      };
      if (!data || typeof data !== "object" || Array.isArray(data))
        throw new ApiError("The service returned unexpected identity context.");
      const row = data as Record<string, unknown>;
      if (
        row.id !== reviewId ||
        !uuid(row.source_id) ||
        !uuid(row.target_id) ||
        !["suggestion", "linked", "reversed"].includes(String(row.state)) ||
        typeof row.reason !== "string" ||
        typeof row.current_reason !== "string" ||
        typeof row.eligible !== "boolean" ||
        typeof row.can_review !== "boolean" ||
        !subject(row.source, row.source_id) ||
        !subject(row.target, row.target_id)
      )
        throw new ApiError("The service returned unexpected identity context.");
      return data as IdentityReviewDetail;
    },
    async savedLists(
      workspaceId: string,
      signal?: AbortSignal,
    ): Promise<SavedList[]> {
      const data = await jsonRequest(
        `/v1/workspaces/${encodeURIComponent(workspaceId)}/lists`,
        { signal },
      );
      if (
        !Array.isArray(data) ||
        data.length > 100 ||
        !data.every((item: unknown) => {
          if (!item || typeof item !== "object" || Array.isArray(item))
            return false;
          const row = item as Record<string, unknown>;
          return (
            typeof row.id === "string" &&
            typeof row.workspace_id === "string" &&
            row.workspace_id === workspaceId &&
            typeof row.name === "string" &&
            row.name.length <= 120 &&
            typeof row.plan_id === "string" &&
            typeof row.created_by === "string" &&
            typeof row.created_at === "string"
          );
        })
      )
        throw new ApiError("The service returned unexpected saved lists.");
      return data as SavedList[];
    },
    async createSavedList(
      workspaceId: string,
      name: string,
      planId: string,
      entityIds: string[],
      signal?: AbortSignal,
    ): Promise<SavedList> {
      if (
        !name.trim() ||
        name.length > 120 ||
        !entityIds.length ||
        entityIds.length > 100
      )
        throw new ApiError(
          "Choose a name and between 1 and 100 results to save.",
        );
      const response = await request(
        `/v1/workspaces/${encodeURIComponent(workspaceId)}/lists`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: name.trim(),
            plan_id: planId,
            entity_ids: entityIds,
          }),
          signal,
        },
        true,
      );
      requireSuccess(response);
      const data = (await response.json()) as Record<string, unknown>;
      if (
        typeof data.id !== "string" ||
        data.workspace_id !== workspaceId ||
        data.plan_id !== planId ||
        typeof data.name !== "string"
      )
        throw new ApiError("The service did not confirm the saved list.");
      return data as SavedList;
    },
    async savedListSnapshot(
      workspaceId: string,
      listId: string,
      revision?: number,
      signal?: AbortSignal,
    ): Promise<SavedListSnapshot> {
      const suffix = revision === undefined ? "latest" : String(revision);
      const data = await jsonRequest(
        `/v1/workspaces/${encodeURIComponent(workspaceId)}/lists/${encodeURIComponent(listId)}/snapshots/${suffix}`,
        { signal },
      );
      if (!data || typeof data !== "object" || Array.isArray(data))
        throw new ApiError(
          "The service returned unexpected saved snapshot data.",
        );
      const row = data as Record<string, unknown>;
      const payload = row.payload as Record<string, unknown> | undefined;
      if (
        row.list_id !== listId ||
        row.workspace_id !== workspaceId ||
        !Number.isInteger(row.revision) ||
        (revision !== undefined && row.revision !== revision) ||
        !payload ||
        !Array.isArray(payload.members) ||
        payload.members.length > 100 ||
        !Array.isArray(payload.omitted) ||
        payload.omitted.length > 100 ||
        payload.refresh_scope !== "persisted_reviewed_facts_only"
      )
        throw new ApiError(
          "The service returned unexpected saved snapshot data.",
        );
      return data as SavedListSnapshot;
    },
    async refreshSavedList(
      workspaceId: string,
      listId: string,
      entityIds: string[],
      expectedRevision: number,
      signal?: AbortSignal,
    ): Promise<SavedListSnapshot> {
      if (
        !entityIds.length ||
        entityIds.length > 100 ||
        !Number.isInteger(expectedRevision) ||
        expectedRevision < 1
      )
        throw new ApiError(
          "This saved list cannot be refreshed with its current revision.",
        );
      const response = await request(
        `/v1/workspaces/${encodeURIComponent(workspaceId)}/lists/${encodeURIComponent(listId)}/refresh`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            entity_ids: entityIds,
            expected_revision: expectedRevision,
          }),
          signal,
        },
        true,
      );
      requireSuccess(response);
      const data = (await response.json()) as Record<string, unknown>;
      if (
        data.list_id !== listId ||
        data.workspace_id !== workspaceId ||
        data.revision !== expectedRevision + 1 ||
        !data.payload ||
        typeof data.payload !== "object"
      )
        throw new ApiError(
          "The service did not confirm the new saved-list revision.",
        );
      return data as SavedListSnapshot;
    },
    async submitFollowup(
      sourceJobId: string,
      workspaceId: string,
      entityId: string,
      question: string,
      signal?: AbortSignal,
    ): Promise<FollowupSubmission> {
      const cleaned = question.trim();
      if (!cleaned || new TextEncoder().encode(cleaned).length > 500)
        throw new ApiError("Enter a question of at most 500 bytes.");
      const response = await request(
        `/v1/jobs/${encodeURIComponent(sourceJobId)}/followups?workspace_id=${encodeURIComponent(workspaceId)}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": globalThis.crypto.randomUUID(),
          },
          body: JSON.stringify({ entity_id: entityId, question: cleaned }),
          signal,
        },
        true,
      );
      requireSuccess(response);
      const data = (await response.json()) as Record<string, unknown>;
      if (
        typeof data.job_id !== "string" ||
        data.workspace_id !== workspaceId ||
        !["queued", "running", "completed", "paused"].includes(
          String(data.state),
        )
      )
        throw new ApiError("The service did not confirm the follow-up job.");
      return data as FollowupSubmission;
    },
    async followupReport(
      jobId: string,
      workspaceId: string,
      signal?: AbortSignal,
    ): Promise<FollowupView> {
      const data = await jsonRequest(
        `/v1/jobs/${encodeURIComponent(jobId)}/report?workspace_id=${encodeURIComponent(workspaceId)}`,
        { signal },
      );
      if (!data || typeof data !== "object" || Array.isArray(data))
        throw new ApiError("The service returned unexpected follow-up data.");
      const row = data as Record<string, unknown>;
      if (
        row.job_id !== jobId ||
        !["pending", "answered", "unknown"].includes(String(row.status)) ||
        !Array.isArray(row.observations) ||
        row.observations.length > 5 ||
        !Array.isArray(row.unknowns) ||
        row.unknowns.length > 10 ||
        row.coverage_complete !== false ||
        row.inference_status !== "unavailable" ||
        row.expansion_status !== "unavailable" ||
        !row.observations.every((value: unknown) => {
          if (!value || typeof value !== "object" || Array.isArray(value))
            return false;
          const item = value as Record<string, unknown>;
          return (
            typeof item.evidence_id === "string" &&
            typeof item.quote === "string" &&
            item.quote.length <= 300 &&
            typeof item.source_url === "string" &&
            Boolean(safeSourceUrl(item.source_url)) &&
            typeof item.collected_at === "string" &&
            Number.isFinite(Date.parse(item.collected_at)) &&
            item.qualification === "source_statement_not_independently_verified"
          );
        })
      )
        throw new ApiError("The service returned unexpected follow-up data.");
      return data as FollowupView;
    },
    async expandResearch(
      sourceJobId: string,
      workspaceId: string,
      prompt: string,
      signal?: AbortSignal,
    ): Promise<ResearchJob> {
      const cleaned = prompt.trim();
      if (cleaned.length < 3 || new TextEncoder().encode(cleaned).length > 1500)
        throw new ApiError("Enter a research prompt of at most 1,500 bytes.");
      const response = await request(
        `/v1/jobs/${encodeURIComponent(sourceJobId)}/expand?workspace_id=${encodeURIComponent(workspaceId)}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": globalThis.crypto.randomUUID(),
          },
          body: JSON.stringify({ prompt: cleaned }),
          signal,
        },
        true,
      );
      requireSuccess(response);
      const data = (await response.json()) as Record<string, unknown>;
      if (
        typeof data.job_id !== "string" ||
        data.workspace_id !== workspaceId ||
        !["queued", "running", "completed", "paused"].includes(
          String(data.state),
        )
      )
        throw new ApiError(
          "The service did not confirm the expanded research run.",
        );
      return {
        id: data.job_id,
        workspace_id: workspaceId,
        status: String(data.state),
      };
    },
    async refineResearch(
      sourceJobId: string,
      workspaceId: string,
      prompt: string,
      signal?: AbortSignal,
    ): Promise<ResearchJob> {
      const cleaned = prompt.trim();
      if (cleaned.length < 3 || new TextEncoder().encode(cleaned).length > 500)
        throw new ApiError("Enter a refinement prompt of at most 500 bytes.");
      const response = await request(
        `/v1/jobs/${encodeURIComponent(sourceJobId)}/refine?workspace_id=${encodeURIComponent(workspaceId)}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": globalThis.crypto.randomUUID(),
          },
          body: JSON.stringify({ prompt: cleaned }),
          signal,
        },
        true,
      );
      requireSuccess(response);
      const data = (await response.json()) as Record<string, unknown>;
      if (
        typeof data.job_id !== "string" ||
        data.workspace_id !== workspaceId ||
        !["queued", "running", "completed", "paused"].includes(
          String(data.state),
        )
      )
        throw new ApiError(
          "The service did not confirm the refined research run.",
        );
      return {
        id: data.job_id,
        workspace_id: workspaceId,
        status: String(data.state),
      };
    },
    async results(
      id: string,
      workspaceId?: string,
      signal?: AbortSignal,
    ): Promise<ResearchResults> {
      const query = workspaceId
        ? `?workspace_id=${encodeURIComponent(workspaceId)}`
        : "";
      const data = await jsonRequest(
        `/v1/jobs/${encodeURIComponent(id)}/results${query}`,
        { signal },
      );
      if (
        !data ||
        typeof data !== "object" ||
        !("job_id" in data) ||
        data.job_id !== id ||
        !("workspace_id" in data) ||
        typeof data.workspace_id !== "string" ||
        (workspaceId && data.workspace_id !== workspaceId) ||
        !("state" in data) ||
        typeof data.state !== "string" ||
        !("results" in data) ||
        !Array.isArray(data.results) ||
        data.results.length > 300 ||
        !("limitations" in data) ||
        !Array.isArray(data.limitations) ||
        !data.limitations.every((item: unknown) => typeof item === "string") ||
        !data.results.every((item: unknown) => {
          if (!item || typeof item !== "object") return false;
          const candidate = item as Record<string, unknown>;
          return (
            ["id", "title", "url", "snippet", "source", "observed_at"].every(
              (key) => typeof candidate[key] === "string",
            ) &&
            candidate.provider === "exa_keyless" &&
            candidate.evidence_kind === "search_snippet" &&
            candidate.qualification === "unverified" &&
            validFit(candidate.fit) &&
            validCollection(candidate.collection) &&
            validExtraction(candidate.extraction) &&
            validFeed(candidate.feed) &&
            validYouTube(candidate.youtube) &&
            (candidate.discussion == null ||
              (typeof candidate.discussion === "object" &&
                ["post", "comment"].includes(
                  String(
                    (candidate.discussion as Record<string, unknown>)
                      .resource_kind,
                  ),
                ) &&
                (candidate.discussion as Record<string, unknown>)
                  .evidence_kind === "indexed_reference" &&
                (candidate.discussion as Record<string, unknown>)
                  .author_handle === null &&
                (candidate.discussion as Record<string, unknown>)
                  .author_identity === "unknown")) &&
            (candidate.platform_reference == null ||
              (typeof candidate.platform_reference === "object" &&
                ["linkedin", "reddit"].includes(
                  String(
                    (candidate.platform_reference as Record<string, unknown>)
                      .source,
                  ),
                ) &&
                [
                  "profile",
                  "company",
                  "post",
                  "comment",
                  "community",
                  "unknown",
                ].includes(
                  String(
                    (candidate.platform_reference as Record<string, unknown>)
                      .resource_kind,
                  ),
                ) &&
                (candidate.platform_reference as Record<string, unknown>)
                  .discovery_backend === "exa_keyless" &&
                (candidate.platform_reference as Record<string, unknown>)
                  .access === "indexed_reference_only" &&
                (candidate.platform_reference as Record<string, unknown>)
                  .direct_read_status === "not_attempted" &&
                (candidate.platform_reference as Record<string, unknown>)
                  .subject_identity === "unknown")) &&
            Array.isArray(candidate.provenance) &&
            candidate.provenance.length <= 200 &&
            candidate.provenance.every((item: unknown) => {
              if (!item || typeof item !== "object") return false;
              const provenance = item as Record<string, unknown>;
              return (
                typeof provenance.source === "string" &&
                typeof provenance.original_url === "string" &&
                typeof provenance.query === "string" &&
                provenance.query.length <= 2000 &&
                typeof provenance.rank === "number" &&
                Number.isInteger(provenance.rank) &&
                provenance.rank > 0 &&
                typeof provenance.observed_at === "string" &&
                provenance.provider === "exa_keyless" &&
                provenance.evidence_kind === "search_snippet"
              );
            })
          );
        }) ||
        !("groups" in data ? validGroups(data.groups, data.results) : true)
      )
        throw new ApiError(
          "The service returned unexpected results. Try checking the run again.",
        );
      return data as ResearchResults;
    },
  };
  return client;
}
