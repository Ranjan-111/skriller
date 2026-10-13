"use client";

import { useEffect, useState } from "react";
import { ExternalLink, RefreshCw } from "lucide-react";
import {
  safeSourceUrl,
  type createApi,
  type ResearchJob,
  type ResearchResults,
  type ResearchRun,
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

  const state = run?.state ?? job.status;
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
