"use client";

import { useEffect, useState } from "react";
import {
  safeSourceUrl,
  type createApi,
  type FollowupView,
  type ResearchCandidate,
} from "../lib/api";

export function FollowupPanel({
  api,
  sourceJobId,
  workspaceId,
  candidate,
}: {
  api: ReturnType<typeof createApi>;
  sourceJobId: string;
  workspaceId: string;
  candidate: ResearchCandidate;
}) {
  const [question, setQuestion] = useState("Why does this result fit?");
  const [jobId, setJobId] = useState("");
  const [report, setReport] = useState<FollowupView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const fit = candidate.fit;
  const hasEvidence =
    fit &&
    [...fit.essential, ...fit.exclusions, ...fit.preferences].some(
      (item) => item.evidence_ids.length > 0,
    );

  useEffect(() => {
    if (!jobId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const started = Date.now();
    async function poll() {
      try {
        const current = await api.followupReport(
          jobId,
          workspaceId,
          controller.signal,
        );
        if (controller.signal.aborted) return;
        setReport(current);
        if (current.status === "pending") {
          if (Date.now() - started < 120_000)
            timer = setTimeout(() => void poll(), 2000);
          else
            setError(
              "Automatic checks paused. Check this report again for its latest status.",
            );
        }
      } catch (failure) {
        if (!controller.signal.aborted)
          setError(
            failure instanceof Error
              ? failure.message
              : "The report could not be checked.",
          );
      }
    }
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [api, jobId, workspaceId, retry]);

  if (!hasEvidence) return null;
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setReport(null);
    try {
      const created = await api.submitFollowup(
        sourceJobId,
        workspaceId,
        candidate.id,
        question,
      );
      setJobId(created.job_id);
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "The follow-up could not be started.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className="candidate-provenance followup-panel">
      <summary>Ask about reviewed evidence</summary>
      <p className="candidate-meta">
        Answers select exact statements from current qualification evidence.
        Source statements are not independently verified.
      </p>
      <form onSubmit={(event) => void submit(event)}>
        <label htmlFor={`followup-${candidate.id}`} className="sr-only">
          Question about {candidate.title}
        </label>
        <input
          id={`followup-${candidate.id}`}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          maxLength={500}
          disabled={busy}
        />
        <button
          type="submit"
          className="text-button"
          disabled={busy || !question.trim()}
        >
          {busy ? "Starting follow-up…" : "Ask follow-up"}
        </button>
      </form>
      {jobId && !report && !error && (
        <p role="status">Checking retained evidence…</p>
      )}
      {report?.status === "pending" && (
        <p role="status">Selecting relevant source statements…</p>
      )}
      {error && (
        <div role="alert">
          <p>{error}</p>
          {jobId && (
            <button
              type="button"
              className="text-button"
              onClick={() => {
                setError("");
                setRetry((value) => value + 1);
              }}
            >
              Check report again
            </button>
          )}
        </div>
      )}
      {report?.status === "answered" && (
        <div aria-live="polite">
          <p>
            Saved source statements ({report.observations.length}). Their
            relevance and coverage have not been independently verified.
          </p>
          {report.observations.map((observation) => (
            <blockquote key={observation.evidence_id}>
              <p>{observation.quote}</p>
              <p className="candidate-meta">
                {observation.source_platform} · Collected{" "}
                {new Date(observation.collected_at).toLocaleString()} · Source
                statement, not independently verified
              </p>
              <a
                href={safeSourceUrl(observation.source_url) ?? undefined}
                target="_blank"
                rel="noopener noreferrer"
              >
                Open source
              </a>
            </blockquote>
          ))}
          <p className="candidate-meta">
            The report does not infer new facts or expand research
            automatically.
          </p>
        </div>
      )}
      {report?.status === "unknown" && (
        <p role="status">
          No supported answer is available from retained qualifying evidence.{" "}
          {report.unknowns.join("; ").replaceAll("_", " ")}.
        </p>
      )}
    </details>
  );
}
