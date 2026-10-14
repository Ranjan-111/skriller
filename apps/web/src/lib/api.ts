import type { components, paths } from "../generated/api";
import { decodeProgress, type ProgressUpdate } from "./progress";

export type SearchPlan = components["schemas"]["SearchPlan"];
export type Capability = components["schemas"]["Capability"];
export type ExecutionContext = components["schemas"]["ExecutionContext"];
export type ProgressEvent = components["schemas"]["ProgressEvent"];
export type SourceDiagnostic = components["schemas"]["SourceDiagnostic"];
export type PlanView = components["schemas"]["PlanView"];
export type JobUsage = components["schemas"]["JobUsage"];
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
  observed_at: string;
  provenance: components["schemas"]["QueryProvenance"][];
  collection?: components["schemas"]["CollectionView"] | null;
  extraction?: components["schemas"]["ExtractionView"] | null;
};
export type ResearchResults = {
  job_id: string;
  workspace_id: string;
  state: string;
  results: ResearchCandidate[];
  limitations: string[];
};
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
        ((typeof fact.value === "string" && fact.value.length <= 4096) ||
          typeof fact.value === "boolean" ||
          (typeof fact.value === "number" && Number.isFinite(fact.value)))
      );
    })
  );
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
            ].every(
              (field) =>
                typeof metric[field] === "number" &&
                Number.isInteger(metric[field]) &&
                metric[field] >= 0,
            ) &&
            [
              "stage_io_seconds",
              "confirmed_cost_usd",
              "estimated_cost_usd",
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
            validCollection(candidate.collection) &&
            validExtraction(candidate.extraction) &&
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
        })
      )
        throw new ApiError(
          "The service returned unexpected results. Try checking the run again.",
        );
      return data as ResearchResults;
    },
  };
  return client;
}
