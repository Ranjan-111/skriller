import type { components } from "../generated/api";

export type AnalyticsGrant = components["schemas"]["GrantOutput"];
export type AnalyticsReport = components["schemas"]["AnalyticsReport"];
export type AnalyticsRequest = components["schemas"]["ReportRequest"];
export type AnalyticsSummary = components["schemas"]["SummaryOutput"];
type Consent = components["schemas"]["ConsentOutput"];
const units: Record<string, string> = {
  views: "count",
  estimatedMinutesWatched: "minutes",
  averageViewDuration: "seconds",
};
const uuid = (value: unknown): value is string =>
  typeof value === "string" &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
const date = (value: unknown): value is string =>
  typeof value === "string" && Number.isFinite(Date.parse(value));
function grant(value: unknown, workspace: string): value is AnalyticsGrant {
  if (!value || typeof value !== "object") return false;
  const row = value as AnalyticsGrant;
  return (
    Object.keys(row).every((key) =>
      [
        "id",
        "workspace_id",
        "created_by",
        "state",
        "channel_id",
        "scopes",
        "expires_at",
        "access_expires_at",
        "remote_revocation",
      ].includes(key),
    ) &&
    uuid(row.id) &&
    row.workspace_id === workspace &&
    typeof row.created_by === "string" &&
    ["pending", "exchanging", "active", "expired", "revoked"].includes(
      row.state,
    ) &&
    (row.channel_id === null || /^UC[A-Za-z0-9_-]{22}$/.test(row.channel_id)) &&
    Array.isArray(row.scopes) &&
    row.scopes.every((scope) => typeof scope === "string") &&
    date(row.expires_at) &&
    (row.access_expires_at === null || date(row.access_expires_at)) &&
    row.remote_revocation === "not_performed"
  );
}
export function consentState(value: Consent): string {
  const url = new URL(value.authorization_url);
  const state = url.searchParams.get("state") || "";
  if (
    !uuid(value.grant_id) ||
    url.origin !== "https://accounts.google.com" ||
    !!url.username ||
    !!url.password ||
    !!url.hash ||
    url.pathname !== "/o/oauth2/v2/auth" ||
    !/^[A-Za-z0-9_-]{32,128}$/.test(state) ||
    !date(value.expires_at) ||
    Date.parse(value.expires_at) <= Date.now()
  )
    throw new Error(
      "The analytics consent response is invalid. Try connecting again.",
    );
  return state;
}
export function createAnalyticsClient(
  request: (path: string, init?: RequestInit) => Promise<unknown>,
) {
  const path = (workspace: string) =>
    `/v1/workspaces/${encodeURIComponent(workspace)}/youtube-analytics`;
  const post = (body?: unknown): RequestInit => ({
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  async function checkGrant(
    workspace: string,
    route: string,
    body: unknown,
    expectedId: string,
  ) {
    const result = await request(path(workspace) + route, post(body));
    if (!grant(result, workspace) || result.id !== expectedId)
      throw new Error("Unexpected analytics connection response.");
    return result;
  }
  return {
    async analyticsGrants(workspace: string) {
      const data = await request(path(workspace) + "/grants");
      if (
        !Array.isArray(data) ||
        data.length > 100 ||
        !data.every((row) => grant(row, workspace))
      )
        throw new Error("Unexpected analytics connection response.");
      return data as AnalyticsGrant[];
    },
    async analyticsStart(workspace: string) {
      const data = (await request(
        path(workspace) + "/oauth/start",
        post({ opt_in: true }),
      )) as Consent;
      consentState(data);
      return data;
    },
    analyticsComplete: (
      workspace: string,
      grantId: string,
      state: string,
      code: string,
    ) =>
      checkGrant(
        workspace,
        "/oauth/complete",
        {
          grant_id: grantId,
          state,
          code,
        },
        grantId,
      ),
    analyticsRevoke: (workspace: string, id: string) =>
      checkGrant(
        workspace,
        `/grants/${encodeURIComponent(id)}/revoke`,
        undefined,
        id,
      ),
    analyticsRefresh: (workspace: string, id: string) =>
      checkGrant(
        workspace,
        `/grants/${encodeURIComponent(id)}/refresh`,
        undefined,
        id,
      ),
    async analyticsReport(
      workspace: string,
      selected: AnalyticsGrant,
      query: AnalyticsRequest,
    ) {
      const data = (await request(
        path(workspace) + `/grants/${encodeURIComponent(selected.id)}/reports`,
        post(query),
      )) as AnalyticsReport;
      if (
        !data ||
        data.grant_id !== selected.id ||
        data.channel_id !== selected.channel_id ||
        data.start_date !== query.start_date ||
        data.end_date !== query.end_date ||
        !["available", "partial", "unavailable"].includes(data.status) ||
        data.timezone !== "America/Los_Angeles" ||
        data.currency !== null ||
        data.coverage_complete !== false ||
        data.availability !== "provider_returned_days_only" ||
        data.summary_status !== "literal_metrics_only" ||
        data.source_platform !== "youtube_analytics" ||
        !date(data.collected_at) ||
        (data.response_sha256 !== null &&
          !/^[a-f0-9]{64}$/.test(data.response_sha256)) ||
        !Array.isArray(data.rows) ||
        data.rows.length > 31 ||
        !Array.isArray(data.summary) ||
        !data.summary.every(
          (line) => typeof line === "string" && line.length <= 2000,
        ) ||
        !data.units ||
        typeof data.units !== "object" ||
        Array.isArray(data.units) ||
        !data.unavailable_metrics ||
        typeof data.unavailable_metrics !== "object" ||
        Array.isArray(data.unavailable_metrics) ||
        Object.entries(data.unavailable_metrics).some(
          ([key, reason]) =>
            !query.metrics.includes(key) ||
            typeof reason !== "string" ||
            reason.length > 2000,
        ) ||
        Object.entries(data.units).some(
          ([key, unit]) => units[key] !== unit || !query.metrics.includes(key),
        ) ||
        !data.rows.every(
          (row) =>
            row &&
            typeof row === "object" &&
            /^\d{4}-\d{2}-\d{2}$/.test(row.day) &&
            row.day >= query.start_date &&
            row.day <= query.end_date &&
            row &&
            row.metrics &&
            typeof row.metrics === "object" &&
            !Array.isArray(row.metrics) &&
            Object.entries(row.metrics).every(
              ([key, value]) =>
                query.metrics.includes(key) &&
                units[key] &&
                data.units[key] === units[key] &&
                typeof value === "number" &&
                Number.isFinite(value) &&
                value >= 0,
            ),
        ) ||
        new Set(data.rows.map((row) => row.day)).size !== data.rows.length
      )
        throw new Error(
          "Unexpected analytics report. No metrics have been displayed.",
        );
      return data;
    },
    async analyticsSummaryStart(
      workspace: string,
      selected: AnalyticsGrant,
      query: AnalyticsRequest,
      idempotencyKey: string,
    ): Promise<AnalyticsSummary> {
      const result = (await request(
        path(workspace) + "/summary-jobs",
        {
          ...post({ grant_id: selected.id, report: query }),
          headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
        },
      )) as AnalyticsSummary;
      if (!result || !uuid(result.job_id) || typeof result.state !== "string" || typeof result.summary_state !== "string" || (result.result != null && !validResearchReport(result.result)))
        throw new Error("Unexpected private summary response.");
      return result;
    },
    async analyticsSummaryGet(workspace: string, jobId: string): Promise<AnalyticsSummary> {
      const result = (await request(path(workspace) + `/summary-jobs/${encodeURIComponent(jobId)}`)) as AnalyticsSummary;
      if (!result || result.job_id !== jobId || typeof result.state !== "string" || typeof result.summary_state !== "string" || (result.result != null && !validResearchReport(result.result)))
        throw new Error("Unexpected private summary response.");
      return result;
    },
    async analyticsSummaryCancel(workspace: string, jobId: string): Promise<AnalyticsSummary> {
      const result = (await request(path(workspace) + `/summary-jobs/${encodeURIComponent(jobId)}/cancel`, post())) as AnalyticsSummary;
      if (!result || result.job_id !== jobId || typeof result.state !== "string" || typeof result.summary_state !== "string" || (result.result != null && !validResearchReport(result.result)))
        throw new Error("Unexpected private summary response.");
      return result;
    },
  };
}

function validResearchReport(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  const report = value as components["schemas"]["ResearchReport"];
  return Object.keys(report).every((key) => ["status", "coverage_complete", "expansion_status", "inference_status", "inferences", "observations", "unknowns", "supplied_evidence_count", "used_evidence_count"].includes(key)) && typeof report.status === "string" && typeof report.coverage_complete === "boolean" && Array.isArray(report.observations) && report.observations.length <= 100 && report.observations.every((row) => row && Object.keys(row).every((key) => ["collected_at", "content_hash_status", "evidence_id", "excerpt_sha256", "qualification", "quote", "source_platform", "source_url", "stored_content_sha256"].includes(key)) && typeof row.quote === "string" && row.quote.length <= 2000 && typeof row.source_url === "string" && /^https:\/\//.test(row.source_url) && typeof row.source_platform === "string" && typeof row.evidence_id === "string") && Array.isArray(report.unknowns) && report.unknowns.every((item) => typeof item === "string" && item.length <= 1000);
}
