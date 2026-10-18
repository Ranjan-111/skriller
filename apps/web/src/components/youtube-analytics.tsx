"use client";

import { useEffect, useRef, useState } from "react";
import type { createApi } from "../lib/api";
import {
  captureCallback,
  CONSENT_KEY,
  consumeConsent,
  type ConsentCallback,
} from "../lib/analytics-consent";
import {
  consentState,
  type AnalyticsGrant,
  type AnalyticsReport,
} from "../lib/youtube-analytics";

const metrics = ["views", "estimatedMinutesWatched", "averageViewDuration"];
const labels: Record<string, string> = {
  views: "Views",
  estimatedMinutesWatched: "Watch time",
  averageViewDuration: "Average view duration",
};

export function YouTubeAnalyticsPanel({
  api,
  userId,
  identityStatus,
  navigate = (url: string) => window.location.assign(url),
}: {
  api: ReturnType<typeof createApi>;
  userId?: string;
  identityStatus: string;
  navigate?: (url: string) => void;
}) {
  const [context, setContext] = useState<{
    uid: string;
    workspace: string;
    owner: boolean;
  } | null>(null);
  const [grants, setGrants] = useState<AnalyticsGrant[]>([]);
  const [selected, setSelected] = useState("");
  const [report, setReport] = useState<AnalyticsReport | null>(null);
  const [privateSummary, setPrivateSummary] = useState<
    import("../lib/youtube-analytics").AnalyticsSummary | null
  >(null);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [reload, setReload] = useState(0);
  const [workspaceRetry, setWorkspaceRetry] = useState(0);
  const callback = useRef<ConsentCallback | null>(null);
  const captured = useRef(false);
  const epoch = useRef(0);
  const summaryKey = useRef<{ signature: string; key: string } | null>(null);
  const cancelledSummary = useRef<string | null>(null);
  useEffect(() => {
    if (captured.current) return;
    captured.current = true;
    if (
      [
        "/connections/salesforce/callback",
        "/connections/x/callback",
        "/connections/reddit/callback",
      ].includes(window.location.pathname)
    )
      return;
    const result = captureCallback(window.location.href);
    if (result) {
      callback.current = result.callback;
      setExpanded(true);
      window.history.replaceState(window.history.state, "", result.cleanUrl);
    }
  }, []);
  useEffect(() => {
    const generation = ++epoch.current;
    setContext(null);
    setGrants([]);
    setReport(null);
    setPrivateSummary(null);
    summaryKey.current = null;
    cancelledSummary.current = null;
    setError("");
    setBusy(false);
    if (identityStatus === "loading") return;
    if (!userId || identityStatus !== "signed_in") {
      if (callback.current) {
        callback.current = null;
        try {
          sessionStorage.removeItem(CONSENT_KEY);
        } catch {
          /* Storage may be disabled. */
        }
      }
      return;
    }
    void api
      .allowance()
      .then((value) => {
        if (generation !== epoch.current) return;
        setContext({
          uid: userId,
          workspace: value.workspace_id,
          owner: value.can_manage,
        });
      })
      .catch(() => {
        if (generation === epoch.current)
          setError("Analytics workspace could not be loaded. Try again.");
      });
    return () => {
      epoch.current++;
    };
  }, [api, userId, identityStatus, workspaceRetry]);
  useEffect(() => {
    if (!context || context.uid !== userId) return;
    if (!context.owner) {
      callback.current = null;
      try {
        sessionStorage.removeItem(CONSENT_KEY);
      } catch {
        /* No stored consent can be reused. */
      }
      return;
    }
    let active = true;
    const generation = epoch.current;
    setBusy(true);
    void (async () => {
      if (callback.current) {
        const result = callback.current;
        callback.current = null;
        const intent = consumeConsent(
          sessionStorage,
          result,
          context.uid,
          context.workspace,
        );
        const completed = await api.analyticsComplete(
          context.workspace,
          intent.grant,
          intent.state,
          result.code!,
        );
        if (
          completed.id !== intent.grant ||
          completed.created_by !== context.uid
        )
          throw new Error("Unexpected analytics connection owner.");
      }
      const rows = await api.analyticsGrants(context.workspace);
      if (rows.some((row) => row.created_by !== context.uid))
        throw new Error("Unexpected analytics connection owner.");
      if (active && generation === epoch.current) {
        setGrants(rows);
        setSelected((previous) =>
          rows.some((row) => row.id === previous)
            ? previous
            : (rows.find((row) => row.state === "active")?.id ??
              rows[0]?.id ??
              ""),
        );
      }
    })()
      .catch((reason) => {
        if (active && generation === epoch.current)
          setError(
            reason instanceof Error
              ? reason.message
              : "Analytics connections could not be loaded.",
          );
      })
      .finally(() => {
        if (active && generation === epoch.current) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [api, context, userId, reload]);

  if (!userId || identityStatus !== "signed_in") return null;
  const current = context?.uid === userId ? context : null;
  const chosen = grants.find((grant) => grant.id === selected);
  const days = (Date.parse(end) - Date.parse(start)) / 86400000;
  const pacificToday = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Los_Angeles",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  const valid =
    /^\d{4}-\d{2}-\d{2}$/.test(start) &&
    /^\d{4}-\d{2}-\d{2}$/.test(end) &&
    days >= 0 &&
    days < 31 &&
    end < pacificToday;
  async function action(operation: () => Promise<void>) {
    const generation = epoch.current;
    setBusy(true);
    setError("");
    try {
      await operation();
    } catch (reason) {
      if (generation === epoch.current)
        setError(
          reason instanceof Error
            ? reason.message
            : "Analytics request failed. Try again.",
        );
    } finally {
      if (generation === epoch.current) setBusy(false);
    }
  }
  return (
    <details
      className="workspace-allowance analytics-panel"
      open={expanded}
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary>YouTube owner analytics</summary>
      <p>
        Connect a channel you own to read its private daily metrics. These
        reports stay separate from lead research.
      </p>
      {error && <p role="alert">{error}</p>}
      {!current ? (
        <button
          type="button"
          className="text-button"
          disabled={!error}
          onClick={() => {
            setWorkspaceRetry((value) => value + 1);
          }}
        >
          {error
            ? "Retry analytics workspace"
            : "Checking analytics workspace…"}
        </button>
      ) : !current.owner ? (
        <p>Only the workspace owner can connect and read channel analytics.</p>
      ) : (
        <>
          <div className="analytics-actions">
            <button
              type="button"
              className="text-button"
              disabled={busy}
              onClick={() =>
                void action(async () => {
                  const generation = epoch.current;
                  const consent = await api.analyticsStart(current.workspace);
                  if (generation !== epoch.current) return;
                  const state = consentState(consent);
                  const target = new URL(consent.authorization_url);
                  const redirect = new URL(
                    target.searchParams.get("redirect_uri") || "",
                  );
                  if (
                    redirect.username ||
                    redirect.password ||
                    redirect.origin !== window.location.origin ||
                    !["/", "/connections/youtube-analytics/callback"].includes(
                      redirect.pathname,
                    ) ||
                    redirect.search ||
                    redirect.hash
                  )
                    throw new Error(
                      "Analytics callback must return to this page. Ask the operator to check the redirect URI.",
                    );
                  sessionStorage.setItem(
                    CONSENT_KEY,
                    JSON.stringify({
                      uid: userId,
                      workspace: current.workspace,
                      grant: consent.grant_id,
                      state,
                      expires: Date.parse(consent.expires_at),
                    }),
                  );
                  navigate(consent.authorization_url);
                })
              }
            >
              Connect owned channel
            </button>
            <button
              type="button"
              className="text-button"
              disabled={busy}
              onClick={() => {
                setReport(null);
                setError("");
                setReload((value) => value + 1);
              }}
            >
              Reload connections
            </button>
          </div>
          {grants.length === 0 ? (
            <p>
              {busy
                ? "Loading channel connections…"
                : "No owned channel is connected yet."}
            </p>
          ) : (
            <>
              <label>
                Channel connection
                <select
                  value={selected}
                  disabled={busy}
                  onChange={(event) => {
                    setSelected(event.target.value);
                    setReport(null);
                    setPrivateSummary(null);
                    setError("");
                  }}
                >
                  {grants.map((grant) => (
                    <option key={grant.id} value={grant.id}>
                      {grant.channel_id || "Consent pending"} · {grant.state}
                    </option>
                  ))}
                </select>
              </label>
              {chosen && (
                <div className="analytics-actions">
                  <button
                    type="button"
                    className="text-button"
                    disabled={
                      busy ||
                      chosen.state === "revoked" ||
                      chosen.state === "pending"
                    }
                    onClick={() =>
                      void action(async () => {
                        setReport(null);
                        setPrivateSummary(null);
                        await api.analyticsRefresh(
                          current.workspace,
                          chosen.id,
                        );
                        setReload((value) => value + 1);
                      })
                    }
                  >
                    Refresh channel access
                  </button>
                  <button
                    type="button"
                    className="text-button"
                    disabled={busy || chosen.state === "revoked"}
                    onClick={() =>
                      void action(async () => {
                        setReport(null);
                        setPrivateSummary(null);
                        await api.analyticsRevoke(current.workspace, chosen.id);
                        setReload((value) => value + 1);
                      })
                    }
                  >
                    Disconnect channel
                  </button>
                </div>
              )}
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!valid || busy || !chosen || chosen.state !== "active")
                    return;
                  const generation = epoch.current;
                  setReport(null);
                  void action(async () => {
                    const value = await api.analyticsReport(
                      current.workspace,
                      chosen,
                      { start_date: start, end_date: end, metrics },
                    );
                    if (generation === epoch.current) setReport(value);
                  });
                }}
              >
                <div className="analytics-dates">
                  <label>
                    From
                    <input
                      type="date"
                      value={start}
                      disabled={busy}
                      onChange={(event) => {
                        setStart(event.target.value);
                        setReport(null);
                        setPrivateSummary(null);
                      }}
                    />
                  </label>
                  <label>
                    Through
                    <input
                      type="date"
                      value={end}
                      disabled={busy}
                      onChange={(event) => {
                        setEnd(event.target.value);
                        setReport(null);
                        setPrivateSummary(null);
                      }}
                    />
                  </label>
                </div>
                <p>Choose up to 31 completed days, using Pacific time.</p>
                <button
                  type="submit"
                  className="text-button"
                  disabled={busy || !valid || chosen?.state !== "active"}
                >
                  {busy ? "Loading analytics…" : "Read daily report"}
                </button>
              </form>
            </>
          )}
          {report && (
            <section aria-label="Owned channel daily report">
              <h3>Daily channel report</h3>
              <p>
                {report.start_date} through {report.end_date} ·{" "}
                {report.timezone}
              </p>
              <p>
                Only provider-returned days are shown. Missing days are unknown,
                not zero.
              </p>
              {report.rows.length === 0 ? (
                <p>No daily metrics were returned for this range.</p>
              ) : (
                <div className="analytics-table">
                  <table>
                    <caption>Channel {report.channel_id}</caption>
                    <thead>
                      <tr>
                        <th scope="col">Day</th>
                        {metrics.map((metric) => (
                          <th scope="col" key={metric}>
                            {labels[metric]} (
                            {report.units[metric] || "unavailable"})
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {report.rows.map((row) => (
                        <tr key={row.day}>
                          <th scope="row">{row.day}</th>
                          {metrics.map((metric) => (
                            <td key={metric}>
                              {row.metrics[metric] ?? "Unavailable"}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {Object.entries(report.unavailable_metrics).map(([metric]) => (
                <p key={metric}>{labels[metric] || metric}: unavailable.</p>
              ))}
              <ul>
                {report.summary.map((line, index) => (
                  <li key={index}>{line}</li>
                ))}
              </ul>
              <p>
                Literal metric summary · collected {report.collected_at}.
                Disconnecting removes access locally; Google permission
                revocation is separate.
              </p>
              <div className="analytics-actions">
                <button
                  type="button"
                  className="text-button"
                  disabled={
                    busy ||
                    !chosen ||
                    chosen.state !== "active" ||
                    Boolean(
                      privateSummary &&
                      ["queued", "running"].includes(privateSummary.state),
                    )
                  }
                  onClick={() =>
                    void action(async () => {
                      if (!chosen) return;
                      const generation = epoch.current;
                      const query = {
                        start_date: report.start_date,
                        end_date: report.end_date,
                        metrics,
                      };
                      const signature = `${current.uid}:${current.workspace}:${chosen.id}:${JSON.stringify(query)}`;
                      if (
                        !summaryKey.current ||
                        summaryKey.current.signature !== signature
                      )
                        summaryKey.current = {
                          signature,
                          key: globalThis.crypto.randomUUID(),
                        };
                      cancelledSummary.current = null;
                      let result =
                        privateSummary &&
                        ["queued", "running"].includes(privateSummary.state)
                          ? await api.analyticsSummaryGet(
                              current.workspace,
                              privateSummary.job_id,
                            )
                          : await api.analyticsSummaryStart(
                              current.workspace,
                              chosen,
                              query,
                              summaryKey.current.key,
                            );
                      if (generation !== epoch.current) return;
                      setPrivateSummary(result);
                      const deadline = Date.now() + 120_000;
                      while (
                        ["queued", "running"].includes(result.state) &&
                        Date.now() < deadline &&
                        cancelledSummary.current !== result.job_id
                      ) {
                        await new Promise((resolve) =>
                          setTimeout(resolve, 1500),
                        );
                        if (generation !== epoch.current) return;
                        result = await api.analyticsSummaryGet(
                          current.workspace,
                          result.job_id,
                        );
                        if (
                          generation === epoch.current &&
                          cancelledSummary.current !== result.job_id
                        )
                          setPrivateSummary(result);
                      }
                    })
                  }
                >
                  {privateSummary &&
                  ["queued", "running"].includes(privateSummary.state)
                    ? "Check summary status"
                    : "Generate private model summary"}
                </button>
                {privateSummary &&
                  ["queued", "running"].includes(privateSummary.state) && (
                    <button
                      type="button"
                      className="text-button"
                      onClick={() => {
                        const jobId = privateSummary.job_id;
                        const generation = epoch.current;
                        cancelledSummary.current = jobId;
                        void api
                          .analyticsSummaryCancel(current.workspace, jobId)
                          .then((result) => {
                            if (generation === epoch.current)
                              setPrivateSummary(result);
                          })
                          .catch((reason) => {
                            if (generation === epoch.current) {
                              cancelledSummary.current = null;
                              setError(
                                reason instanceof Error
                                  ? reason.message
                                  : "Summary could not be cancelled.",
                              );
                            }
                          });
                      }}
                    >
                      Cancel summary
                    </button>
                  )}
              </div>
              {privateSummary && (
                <section
                  aria-label="Private channel summary"
                  aria-live="polite"
                >
                  <h3>Private model summary · {privateSummary.state}</h3>
                  {privateSummary.state === "queued" ||
                  privateSummary.state === "running" ? (
                    <p>
                      Summary is being prepared from the selected owner report.
                      It stays private to your account.
                    </p>
                  ) : null}
                  {privateSummary.result && (
                    <>
                      <p>
                        {privateSummary.result.status}. This summary uses{" "}
                        {privateSummary.result.used_evidence_count} of{" "}
                        {privateSummary.result.supplied_evidence_count} supplied
                        observations; it is not shared with lead research.
                      </p>
                      {privateSummary.result.observations.map((item) => (
                        <blockquote key={item.evidence_id}>
                          <p>{item.quote}</p>
                          <a
                            href={item.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            {item.source_platform} source
                          </a>
                          <p>
                            Observed {item.collected_at} ·{" "}
                            {item.qualification.replaceAll("_", " ")}
                          </p>
                        </blockquote>
                      ))}
                      {privateSummary.result.unknowns.map((item, index) => (
                        <p key={index}>Unknown: {item}</p>
                      ))}
                    </>
                  )}
                  {["failed", "cancelled", "paused"].includes(
                    privateSummary.state,
                  ) && (
                    <p role="status">
                      Summary {privateSummary.state}. Your literal report
                      remains available; retry when ready.
                    </p>
                  )}
                </section>
              )}
            </section>
          )}
        </>
      )}
    </details>
  );
}
