import type { components, paths } from "../generated/api";
import { decodeProgress, type ProgressUpdate } from "./progress";

export type SearchPlan = components["schemas"]["SearchPlan"];
export type Capability = components["schemas"]["Capability"];
export type ExecutionContext = components["schemas"]["ExecutionContext"];
export type ProgressEvent = components["schemas"]["ProgressEvent"];
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
          ? "The workspace has reached its run limit. Try again later."
          : "The research request could not be started. Your prompt is kept here; try again.",
        response.status,
      );
  }
  const client = {
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
            candidate.qualification === "unverified"
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
