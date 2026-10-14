"use client";

import { useEffect, useState } from "react";
import { ExternalLink, RefreshCw } from "lucide-react";
import {
  safeSourceUrl,
  type createApi,
  type ResearchJob,
  type ResearchResults,
  type ResearchRun,
  type PlanView,
  type JobUsage,
  type SourceDiagnostic,
} from "../lib/api";

import { downloadSources, SOURCE_EXPORT_LIMIT } from "../lib/exports";

const finished = new Set([
  "completed",
  "partial",
  "failed",
  "cancelled",
  "paused",
  "waiting_for_connection",
]);
const labels: Record<string, string> = {
  accepted: "Run accepted",
  queued: "Research queued",
  running: "Research in progress",
  completed: "Research complete",
  partial: "Research finished with partial results",
  failed: "Research could not finish",
  cancelled: "Research cancelled",
  paused: "Research paused",
  waiting_for_connection: "A source connection is needed",
};

export function ResearchResultsPanel({
  api,
  job,
}: {
  api: ReturnType<typeof createApi>;
  job: ResearchJob;
}) {
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [results, setResults] = useState<ResearchResults | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [cancelling, setCancelling] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [sourceDiagnostics, setSourceDiagnostics] = useState<
    SourceDiagnostic[] | null
  >(null);
  const [sourceError, setSourceError] = useState("");
  const [plan, setPlan] = useState<PlanView | null>(null);
  const [planError, setPlanError] = useState("");
  const [usage, setUsage] = useState<JobUsage | null>(null);
  const [usageError, setUsageError] = useState("");
  const [usageOpen, setUsageOpen] = useState(false);
  async function loadSourceReadiness() {
    if (!job.workspace_id) return;
    setSourceError("");
    setSourceDiagnostics(null);
    try {
      setSourceDiagnostics(await api.sourceDiagnostics(job.workspace_id));
    } catch (failure) {
      setSourceError(
        failure instanceof Error
          ? failure.message
          : "Unable to check source readiness.",
      );
    }
  }
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let lastCount = -1;
    const started = Date.now();
    setError("");
    async function poll() {
      try {
        const snapshot = await api.job(
          job.id,
          job.workspace_id,
          controller.signal,
        );
        if (controller.signal.aborted) return;
        setRun(snapshot);
        if (
          snapshot.result_count !== lastCount ||
          finished.has(snapshot.state)
        ) {
          const page = await api.results(
            job.id,
            job.workspace_id,
            controller.signal,
          );
          if (controller.signal.aborted) return;
          setResults(page);
          lastCount = snapshot.result_count;
        }
        if (!finished.has(snapshot.state)) {
          if (Date.now() - started >= 15 * 60 * 1000) {
            setError(
              "Automatic checks paused after 15 minutes. Check this run again for its latest status.",
            );
          } else {
            timer = setTimeout(() => void poll(), 2000);
          }
        }
      } catch (e) {
        if (!controller.signal.aborted)
          setError(
            e instanceof Error
              ? e.message
              : "Unable to check this run. Try again.",
          );
      }
    }
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [api, job.id, job.workspace_id, retry]);

  useEffect(() => {
    if (!job.workspace_id) return;
    const controller = new AbortController();
    setPlan(null);
    setPlanError("");
    void api
      .plan(job.id, job.workspace_id, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setPlan(value);
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) {
          setPlanError(
            failure instanceof Error
              ? failure.message
              : "Unable to load the interpreted request.",
          );
        }
      });
    return () => controller.abort();
  }, [api, job.id, job.workspace_id]);

  const state = run?.state ?? job.status;
  async function showSourceReadiness() {
    if (sourcesOpen) {
      setSourcesOpen(false);
      return;
    }
    setSourcesOpen(true);
    if (!job.workspace_id || sourceDiagnostics) return;
    await loadSourceReadiness();
  }
  async function showUsage() {
    if (usageOpen) {
      setUsageOpen(false);
      return;
    }
    setUsageOpen(true);
    if (!job.workspace_id || usage) return;
    setUsageError("");
    try {
      setUsage(await api.usage(job.id, job.workspace_id));
    } catch (failure) {
      setUsageError(
        failure instanceof Error
          ? failure.message
          : "Unable to load run usage.",
      );
    }
  }
  return (
    <section className="research-results" aria-labelledby="run-title">
      <div className="run-summary" role="status" aria-live="polite">
        <h2 id="run-title">{labels[state] ?? "Checking research status"}</h2>
        {run?.stage && <p>Current stage: {run.stage.replaceAll("_", " ")}</p>}
        <p className="run-reference">Run {job.id}</p>
        {!finished.has(state) && (
          <button
            className="text-button"
            type="button"
            disabled={cancelling}
            onClick={async () => {
              setCancelling(true);
              setError("");
              try {
                await api.cancel(job.id, job.workspace_id);
                setRetry((value) => value + 1);
              } catch (failure) {
                setError(
                  failure instanceof Error
                    ? failure.message
                    : "Cancellation was not confirmed.",
                );
              } finally {
                setCancelling(false);
              }
            }}
          >
            {cancelling ? "Stopping research…" : "Stop research"}
          </button>
        )}
      </div>
      {job.workspace_id && (
        <section className="interpreted-plan" aria-labelledby="plan-title">
          <h3 id="plan-title">What this run understood</h3>
          {planError ? (
            <p role="status">{planError}</p>
          ) : !plan ? (
            <p role="status">Loading the saved interpretation…</p>
          ) : (
            <>
              <p>Interpretation status: {plan.status.replaceAll("_", " ")}</p>
              {plan.interpretation.clarification && (
                <p className="notice" role="status">
                  {plan.interpretation.clarification}
                </p>
              )}
              {(plan.interpretation.unsupported_criteria ?? []).length > 0 && (
                <div>
                  <h4>Criteria this run cannot evaluate</h4>
                  <ul>
                    {(plan.interpretation.unsupported_criteria ?? []).map(
                      (item, index) => (
                        <li key={`${index}-${item}`}>{item}</li>
                      ),
                    )}
                  </ul>
                </div>
              )}
              {(["must_have", "preferences", "exclusions"] as const).map(
                (group) => {
                  const criteria = plan.interpretation[group] ?? [];
                  if (!criteria.length) return null;
                  const heading =
                    group === "must_have"
                      ? "Required"
                      : group === "preferences"
                        ? "Preferred"
                        : "Excluded";
                  return (
                    <div key={group}>
                      <h4>{heading}</h4>
                      <ul>
                        {criteria.map((criterion, index) => (
                          <li key={`${criterion.field}-${index}`}>
                            {criterion.field.replaceAll("_", " ")}{" "}
                            {criterion.operator.replaceAll("_", " ")}{" "}
                            {Array.isArray(criterion.value)
                              ? criterion.value.join(", ")
                              : String(criterion.value)}
                          </li>
                        ))}
                      </ul>
                    </div>
                  );
                },
              )}
              <p className="candidate-meta">
                Sources:{" "}
                {(plan.interpretation.sources ?? []).join(", ") ||
                  "none selected"}
                . These are search criteria, not verified facts.
              </p>
            </>
          )}
        </section>
      )}
      {job.workspace_id && (
        <div className="run-usage">
          <button
            className="text-button"
            type="button"
            aria-expanded={usageOpen}
            aria-controls="run-usage-details"
            onClick={() => void showUsage()}
          >
            {usageOpen ? "Hide run usage" : "Show run usage and budget"}
          </button>
          {usageOpen && (
            <div id="run-usage-details" aria-live="polite">
              {usageError ? (
                <div className="notice error" role="alert">
                  <p>{usageError}</p>
                </div>
              ) : !usage ? (
                <p role="status">Loading run usage…</p>
              ) : (
                <>
                  <dl className="usage-summary">
                    <div>
                      <dt>Budget cap</dt>
                      <dd>
                        {usage.budget_cap_usd} {usage.currency}
                      </dd>
                    </div>
                    <div>
                      <dt>Confirmed cost</dt>
                      <dd>
                        {usage.confirmed_cost_usd} {usage.currency}
                      </dd>
                    </div>
                    <div>
                      <dt>Uncertain estimate</dt>
                      <dd>
                        {usage.estimated_cost_usd} {usage.currency}
                      </dd>
                    </div>
                    <div>
                      <dt>Reserved</dt>
                      <dd>
                        {usage.reserved_cost_usd} {usage.currency}
                      </dd>
                    </div>
                    <div>
                      <dt>Remaining after exposure</dt>
                      <dd>
                        {usage.remaining_budget_usd} {usage.currency}
                      </dd>
                    </div>
                  </dl>
                  {usage.stage_metrics.length > 0 && (
                    <section
                      className="stage-metrics"
                      aria-labelledby="stage-metrics-title"
                    >
                      <h4 id="stage-metrics-title">Work by stage</h4>
                      <ul>
                        {usage.stage_metrics.map((metric) => (
                          <li key={`${metric.stage}-${metric.source}`}>
                            <strong>{metric.stage.replaceAll("_", " ")}</strong>
                            <span>{metric.source}</span>
                            <span>
                              {metric.succeeded} succeeded /{" "}
                              {metric.observations} observed
                              {metric.failed > 0
                                ? ` · ${metric.failed} failed`
                                : ""}
                            </span>
                            <span>
                              {metric.stage_io_seconds} seconds stage I/O
                            </span>
                          </li>
                        ))}
                      </ul>
                      {(usage.invalid_stage_observations > 0 ||
                        usage.stage_metrics_truncated) && (
                        <p role="status">
                          Some stage measurements are invalid or omitted from
                          this bounded report.
                        </p>
                      )}
                    </section>
                  )}
                  <p className="candidate-meta">
                    The exposure ceiling combines confirmed charges, uncertain
                    estimates and active reservations. Estimates are not final
                    provider invoices.
                  </p>
                </>
              )}
            </div>
          )}
        </div>
      )}
      {error && (
        <div className="notice error" role="alert">
          <p>{error}</p>
          <button
            type="button"
            className="text-button"
            onClick={() => setRetry((value) => value + 1)}
          >
            Check run again <RefreshCw size={13} aria-hidden="true" />
          </button>
        </div>
      )}
      {state === "paused" && job.workspace_id && (
        <div className="run-recovery">
          <p>
            Saved results are available. You can resume only if the service
            confirms the checkpoint and remaining run budget are safe.
          </p>
          <button
            className="text-button"
            type="button"
            disabled={resuming}
            onClick={async () => {
              setResuming(true);
              setError("");
              try {
                await api.resume(job.id, job.workspace_id!);
                setRetry((value) => value + 1);
              } catch (failure) {
                setError(
                  failure instanceof Error
                    ? failure.message
                    : "The run could not be resumed. Your saved results remain available.",
                );
              } finally {
                setResuming(false);
              }
            }}
          >
            {resuming ? "Checking checkpoint…" : "Resume research"}
          </button>
        </div>
      )}
      {job.workspace_id && (
        <div className="source-readiness">
          <button
            className="text-button"
            type="button"
            aria-expanded={sourcesOpen}
            aria-controls="source-readiness-details"
            onClick={() => void showSourceReadiness()}
          >
            {sourcesOpen ? "Hide source readiness" : "Check source readiness"}
          </button>
          {sourcesOpen && (
            <div id="source-readiness-details" aria-live="polite">
              {sourceError && (
                <div className="notice error" role="alert">
                  <p>{sourceError}</p>
                  <button
                    className="text-button"
                    type="button"
                    onClick={() => void loadSourceReadiness()}
                  >
                    Try again
                  </button>
                </div>
              )}
              {!sourceError && !sourceDiagnostics && (
                <p role="status">Checking workspace source setup…</p>
              )}
              {sourceDiagnostics && (
                <ul className="source-readiness-list">
                  {sourceDiagnostics
                    .filter((item) =>
                      ["linkedin", "reddit", "web"].includes(
                        item.capability.source,
                      ),
                    )
                    .map((item) => (
                      <li
                        key={`${item.capability.source}-${item.capability.operation}`}
                      >
                        <span>
                          {item.capability.source} · {item.capability.operation}
                        </span>
                        <strong>{item.setup_state.replaceAll("_", " ")}</strong>
                        <small>
                          {item.evidence_scope === "public_indexed_references"
                            ? "Public search references; not direct platform access"
                            : item.capability.access_route}
                        </small>
                      </li>
                    ))}
                </ul>
              )}
              <p className="candidate-meta">
                Source status does not test credentials or sign in to a
                platform.
              </p>
            </div>
          )}
        </div>
      )}
      {finished.has(state) &&
        ["failed", "partial", "paused", "waiting_for_connection"].includes(
          state,
        ) && (
          <p>
            Some source requests could not finish. Any results below are
            retained; your prompt is kept above.
          </p>
        )}
      {results && (
        <>
          <h3>Discovered sources ({results.results.length})</h3>
          {results.results.length > 0 && (
            <div
              className="source-exports"
              aria-label="Download search snippets"
            >
              <button
                className="text-button"
                type="button"
                onClick={() => downloadSources(results.results, "json")}
              >
                Download snippets as JSON
              </button>
              <button
                className="text-button"
                type="button"
                onClick={() => downloadSources(results.results, "csv")}
              >
                Download snippets as CSV
              </button>
              {results.results.length > SOURCE_EXPORT_LIMIT && (
                <p>
                  Downloads include the first {SOURCE_EXPORT_LIMIT} sources.
                </p>
              )}
            </div>
          )}
          <p>
            Search snippets are unverified candidates. Check the original source
            before judging fit or using any contact information.
          </p>
          {results.limitations.length > 0 && (
            <ul
              className="result-limitations"
              aria-label="Research limitations"
            >
              {results.limitations.map((text, index) => (
                <li key={index}>{text}</li>
              ))}
            </ul>
          )}
          {results.results.length === 0 ? (
            <p>
              {finished.has(state)
                ? "No matching sources were returned. Try a more specific prompt or different sources."
                : "Searching for matching sources…"}
            </p>
          ) : (
            <ol className="candidate-list">
              {results.results.map((candidate) => {
                const url = safeSourceUrl(candidate.url);
                return (
                  <li key={candidate.id}>
                    <h4>
                      {url ? (
                        <a href={url} target="_blank" rel="noopener noreferrer">
                          {candidate.title || "Untitled source"}{" "}
                          <ExternalLink size={14} aria-hidden="true" />
                          <span className="sr-only"> (opens in a new tab)</span>
                        </a>
                      ) : (
                        candidate.title || "Untitled source"
                      )}
                    </h4>
                    <p className="candidate-meta">
                      {candidate.source} · Search snippet · Unverified
                    </p>
                    <p className="candidate-meta">
                      Retrieved{" "}
                      <time dateTime={candidate.observed_at}>
                        {candidate.observed_at}
                      </time>
                    </p>
                    <p className="candidate-snippet">
                      {candidate.snippet || "No search snippet was provided."}
                    </p>
                    {url ? (
                      <p className="candidate-url">{url}</p>
                    ) : (
                      <p>
                        Source link unavailable: the returned address is unsafe
                        or invalid.
                      </p>
                    )}
                    {candidate.provenance.length > 0 && (
                      <details className="candidate-provenance">
                        <summary>
                          Search references ({candidate.provenance.length})
                        </summary>
                        <p className="candidate-meta">
                          These references explain how this result was found.
                          They do not mean the page was read or the candidate's
                          claims were verified.
                        </p>
                        <ol>
                          {candidate.provenance.map((reference, index) => {
                            const referenceUrl = safeSourceUrl(
                              reference.original_url,
                            );
                            return (
                              <li
                                key={`${reference.source}-${reference.rank}-${index}`}
                              >
                                <span>
                                  {reference.source} · result {reference.rank}
                                </span>
                                <p>{reference.query}</p>
                                {referenceUrl ? (
                                  <a
                                    href={referenceUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                  >
                                    Open search reference{" "}
                                    <ExternalLink
                                      size={13}
                                      aria-hidden="true"
                                    />
                                    <span className="sr-only">
                                      {" "}
                                      (opens in a new tab)
                                    </span>
                                  </a>
                                ) : (
                                  <span>
                                    Reference link unavailable because its
                                    address is unsafe or invalid.
                                  </span>
                                )}
                              </li>
                            );
                          })}
                        </ol>
                      </details>
                    )}
                    {candidate.collection && (
                      <p className="candidate-meta">
                        {candidate.collection.status === "read"
                          ? "Page read"
                          : "Page read unavailable"}
                        {candidate.collection.failure_code
                          ? ` · ${candidate.collection.failure_code.replaceAll("_", " ")}`
                          : ""}
                      </p>
                    )}
                    {candidate.extraction && (
                      <details className="candidate-provenance">
                        <summary>
                          Page observations (
                          {candidate.extraction.observations.length}) ·
                          Unverified
                        </summary>
                        <p className="candidate-meta">
                          Quotes come from the saved page. Subject identity and
                          qualification still need verification.
                        </p>
                        {candidate.extraction.observations.length === 0 && (
                          <p>No supported observations were extracted.</p>
                        )}
                        <ol>
                          {candidate.extraction.observations.map((fact) => (
                            <li key={fact.claim_id}>
                              <strong>
                                {fact.field.replaceAll("_", " ")}:{" "}
                                {String(fact.value)}
                              </strong>
                              <p className="candidate-meta">
                                {fact.status === "conflict"
                                  ? "Conflicting observation"
                                  : fact.status === "accepted"
                                    ? "Verified source fact · Candidate fit pending"
                                    : "Source observation · Unverified"}
                              </p>
                              <blockquote>{fact.quote}</blockquote>
                            </li>
                          ))}
                        </ol>
                        {!candidate.extraction.coverage_complete && (
                          <p>
                            Part of the page was outside this run’s extraction
                            coverage.
                          </p>
                        )}
                        {candidate.extraction.rejected_claims > 0 && (
                          <p>
                            {candidate.extraction.rejected_claims} unsupported
                            model drafts were rejected.
                          </p>
                        )}
                        {(candidate.extraction.expired_observations ?? 0) >
                          0 && (
                          <p>
                            {candidate.extraction.expired_observations}{" "}
                            observations no longer have current retained
                            evidence.
                          </p>
                        )}
                        {candidate.extraction.failure_code && (
                          <p>
                            Extraction stopped:{" "}
                            {candidate.extraction.failure_code.replaceAll(
                              "_",
                              " ",
                            )}
                            .
                          </p>
                        )}
                      </details>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
        </>
      )}
    </section>
  );
}
