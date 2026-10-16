"use client";

import { useEffect, useRef, useState } from "react";
import { ExternalLink, RefreshCw } from "lucide-react";
import {
  safeSourceUrl,
  type createApi,
  type IdentityReview,
  type IdentityReviewDetail,
  type ResearchJob,
  type ResearchResults,
  type ResearchRun,
  type PlanView,
  type JobUsage,
  type SourceDiagnostic,
  type ResearchCandidate,
  type YouTubeView,
} from "../lib/api";

import { downloadSources, SOURCE_EXPORT_LIMIT } from "../lib/exports";
import { SavedListsPanel } from "./saved-lists-panel";
import { CrmDeliveryPanel } from "./crm-delivery-panel";
import { FollowupPanel } from "./followup-panel";
import { ResearchExpansion } from "./research-expansion";
import { ResearchRefinement } from "./research-refinement";
import { ClarificationResponse } from "./clarification-response";

function IdentityReviewPanel({
  api,
  workspaceId,
  onReviewed,
}: {
  api: ReturnType<typeof createApi>;
  workspaceId: string;
  onReviewed: () => void;
}) {
  const [reviews, setReviews] = useState<IdentityReview[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [contexts, setContexts] = useState<
    Record<string, IdentityReviewDetail>
  >({});
  const operations = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    operations.current = controller;
    setReviews(null);
    setContexts({});
    setBusy(null);
    setError("");
    void api
      .identityReviews(workspaceId, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setReviews(value);
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted)
          setError(
            failure instanceof Error
              ? failure.message
              : "Unable to load identity reviews.",
          );
      });
    return () => controller.abort();
  }, [api, workspaceId]);

  async function showContext(review: IdentityReview) {
    const controller = operations.current;
    if (!controller) return;
    setBusy(review.id);
    setError("");
    try {
      const detail = await api.identityReview(
        workspaceId,
        review.id,
        controller.signal,
      );
      if (!controller.signal.aborted)
        setContexts((current) => ({ ...current, [review.id]: detail }));
    } catch (failure) {
      if (!controller.signal.aborted)
        setError(
          failure instanceof Error
            ? failure.message
            : "Identity evidence is unavailable. Try loading it again.",
        );
    } finally {
      if (!controller.signal.aborted) setBusy(null);
    }
  }

  async function change(review: IdentityReview, action: "approve" | "reverse") {
    const controller = operations.current;
    if (!controller) return;
    setBusy(review.id);
    setError("");
    try {
      const updated = await api.changeIdentityReview(
        workspaceId,
        review.id,
        action,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setReviews(
        (current) =>
          current?.map((item) => (item.id === updated.id ? updated : item)) ??
          current,
      );
      onReviewed();
      const detail = await api.identityReview(
        workspaceId,
        review.id,
        controller.signal,
      );
      if (!controller.signal.aborted)
        setContexts((current) => ({ ...current, [review.id]: detail }));
    } catch (failure) {
      if (!controller.signal.aborted)
        setError(
          failure instanceof Error
            ? failure.message
            : "This identity review could not be changed.",
        );
    } finally {
      if (!controller.signal.aborted) setBusy(null);
    }
  }

  return (
    <details className="candidate-provenance identity-reviews">
      <summary>Identity review queue</summary>
      <p className="candidate-meta">
        Suggestions stay separate until a workspace owner approves them. Review
        the underlying people and source evidence before linking; IDs alone do
        not establish identity.
      </p>
      {error && <p role="alert">{error}</p>}
      {!reviews && !error && <p role="status">Loading identity reviews…</p>}
      {reviews?.length === 0 && <p>No identity suggestions are waiting.</p>}
      {reviews && reviews.length > 0 && (
        <ol>
          {reviews.map((review) => (
            <li key={review.id}>
              <strong>{review.state.replaceAll("_", " ")}</strong>
              <p>{review.reason}</p>
              <p className="candidate-meta">
                Record IDs: {review.source_id} · {review.target_id}
              </p>
              {review.review_outcome && <p>{review.review_outcome}</p>}
              <button
                className="text-button"
                type="button"
                disabled={busy !== null}
                onClick={() => void showContext(review)}
              >
                {busy === review.id
                  ? "Loading review…"
                  : "View current identity evidence"}
              </button>
              {contexts[review.id] && (
                <div>
                  <p>
                    Current identity check:{" "}
                    {contexts[review.id].current_reason.replaceAll("_", " ")}
                  </p>
                  {[contexts[review.id].source, contexts[review.id].target].map(
                    (subject) => (
                      <section key={subject.id}>
                        <h4>{subject.display_name}</h4>
                        <p className="candidate-meta">
                          Record type: {subject.kind}. The record name alone is
                          not identity proof.
                        </p>
                        {!subject.available && (
                          <p>This record was removed or is unavailable.</p>
                        )}
                        {!subject.context_complete && (
                          <p>
                            Some identity evidence is unavailable in this view.
                          </p>
                        )}
                        {subject.identity_facts.length === 0 && (
                          <p>No current identity proof is available.</p>
                        )}
                        <ul>
                          {subject.identity_facts.map((fact) => (
                            <li key={fact.claim_id}>
                              <strong>
                                {fact.field.replaceAll("_", " ")}: {fact.value}
                              </strong>
                              {fact.evidence.map((citation) => (
                                <blockquote key={citation.id}>
                                  <p>
                                    {citation.excerpt}
                                    {citation.excerpt_truncated ? "…" : ""}
                                  </p>
                                  <p className="candidate-meta">
                                    {citation.source_platform} · Collected{" "}
                                    {new Date(
                                      citation.collected_at,
                                    ).toLocaleString()}
                                    {citation.expires_at
                                      ? ` · Expires ${new Date(citation.expires_at).toLocaleString()}`
                                      : ""}
                                  </p>
                                  <a
                                    href={
                                      safeSourceUrl(citation.source_url) ??
                                      undefined
                                    }
                                    target="_blank"
                                    rel="noopener noreferrer"
                                  >
                                    Open identity source
                                  </a>
                                </blockquote>
                              ))}
                            </li>
                          ))}
                        </ul>
                      </section>
                    ),
                  )}
                  {!contexts[review.id].can_review && (
                    <p>Only a workspace owner can change these links.</p>
                  )}
                </div>
              )}
              {review.state === "suggestion" &&
                contexts[review.id]?.can_review && (
                  <button
                    className="text-button"
                    type="button"
                    disabled={
                      busy !== null ||
                      !contexts[review.id].eligible ||
                      !contexts[review.id].source.context_complete ||
                      !contexts[review.id].target.context_complete
                    }
                    onClick={() => void change(review, "approve")}
                  >
                    {busy === review.id ? "Saving review…" : "Approve link"}
                  </button>
                )}
              {review.state === "linked" && contexts[review.id]?.can_review && (
                <button
                  className="text-button"
                  type="button"
                  disabled={busy !== null}
                  onClick={() => void change(review, "reverse")}
                >
                  {busy === review.id ? "Saving review…" : "Reverse link"}
                </button>
              )}
            </li>
          ))}
        </ol>
      )}
    </details>
  );
}

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

const fitLabels = {
  confirmed: "Meets required criteria",
  near_match: "Some required details are unknown",
  excluded: "Does not meet an exclusion check",
} as const;

function criterionLabel(
  criterion: NonNullable<
    ResearchCandidate["fit"]
  >["essential"][number]["criterion"],
) {
  const value = Array.isArray(criterion.value)
    ? criterion.value.join(", ")
    : String(criterion.value);
  return `${criterion.field.replaceAll("_", " ")} ${criterion.operator.replaceAll("_", " ")} ${value}`;
}

function CriterionEvidence({
  api,
  jobId,
  workspaceId,
  evidenceId,
}: {
  api: ReturnType<typeof createApi>;
  jobId: string;
  workspaceId?: string;
  evidenceId: string;
}) {
  const [open, setOpen] = useState(false);
  const [citation, setCitation] = useState<Awaited<
    ReturnType<typeof api.evidenceCitation>
  > | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open || !workspaceId || citation) return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    void api
      .evidenceCitation(jobId, evidenceId, workspaceId, controller.signal)
      .then(setCitation)
      .catch((failure: unknown) => {
        if (!controller.signal.aborted)
          setError(
            failure instanceof Error
              ? failure.message
              : "Evidence is unavailable.",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [api, citation, evidenceId, jobId, open, workspaceId]);

  return (
    <div className="criterion-evidence">
      <button
        className="text-button"
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {open ? "Hide supporting source" : "View supporting source"}
      </button>
      {open &&
        (loading ? <p role="status">Loading saved source excerpt…</p> : null)}
      {open && error && (
        <p role="status">
          {error}. This citation may have expired, been removed, or be
          unavailable in this view.
        </p>
      )}
      {open && citation && (
        <blockquote>
          <p>
            {citation.excerpt}
            {citation.excerpt_truncated ? "…" : ""}
          </p>
          <p className="candidate-meta">
            {citation.source_platform} · Collected{" "}
            {new Date(citation.collected_at).toLocaleString()}
            {citation.expires_at
              ? ` · Expires ${new Date(citation.expires_at).toLocaleString()}`
              : ""}
          </p>
          <p className="candidate-meta">
            Content hash is stored metadata and has not been revalidated against
            the source.
          </p>
          <a
            href={safeSourceUrl(citation.source_url) ?? undefined}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open original source <ExternalLink size={13} aria-hidden="true" />
          </a>
        </blockquote>
      )}
    </div>
  );
}

function CandidateFit({
  api,
  jobId,
  workspaceId,
  candidate,
}: {
  api: ReturnType<typeof createApi>;
  jobId: string;
  workspaceId?: string;
  candidate: ResearchCandidate;
}) {
  const fit = candidate.fit;
  if (!fit) return null;
  return (
    <details className="candidate-fit">
      <summary>
        {fit.status === "confirmed"
          ? "Reviewed fit"
          : fit.status === "near_match"
            ? "Possible fit"
            : "Review outcome"}{" "}
        · {fitLabels[fit.status]}
      </summary>
      <p className="candidate-meta">
        This evaluates retained facts about the subject; the search snippet
        itself remains unverified.
      </p>
      {[
        { heading: "Required criteria", criteria: fit.essential },
        { heading: "Exclusion checks", criteria: fit.exclusions },
        { heading: "Preferences", criteria: fit.preferences },
      ]
        .filter(({ criteria }) => criteria.length > 0)
        .map(({ heading, criteria }) => (
          <section key={heading}>
            <h5>{heading}</h5>
            <ul>
              {criteria.map((item, index) => (
                <li key={`${item.criterion.field}-${index}`}>
                  <strong>{criterionLabel(item.criterion)}</strong> ·{" "}
                  {item.outcome.replaceAll("_", " ")}
                  <p>{item.reason}</p>
                  {item.outcome === "unknown" && (
                    <p className="candidate-meta">
                      This criterion could not be verified from current retained
                      evidence.
                    </p>
                  )}
                  {item.evidence_ids.map((evidenceId) => (
                    <CriterionEvidence
                      key={`${jobId}:${evidenceId}`}
                      api={api}
                      jobId={jobId}
                      workspaceId={workspaceId}
                      evidenceId={evidenceId}
                    />
                  ))}
                  {item.evidence_ids.length === 0 && (
                    <p className="candidate-meta">
                      No supporting citation is available.
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </section>
        ))}
      {fit.limitations.length > 0 && (
        <section>
          <h5>Subject and evidence limitations</h5>
          <ul>
            {fit.limitations.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </section>
      )}
      {fit.preferences.length > 0 && (
        <p className="candidate-meta">
          {fit.preference_score} preference
          {fit.preference_score === 1 ? "" : "s"} matched. Preferences affect
          ordering only; this is not a confidence score.
        </p>
      )}
    </details>
  );
}

function YouTubeEvidence({
  api,
  jobId,
  workspaceId,
  youtube,
}: {
  api: ReturnType<typeof createApi>;
  jobId: string;
  workspaceId?: string;
  youtube: YouTubeView;
}) {
  const metadata = youtube.metadata;
  const videoUrl = metadata?.source_url
    ? safeSourceUrl(metadata.source_url)
    : null;
  const timestampedUrl = (seconds: number) => {
    if (!videoUrl) return null;
    try {
      const address = new URL(videoUrl);
      const host = address.hostname.toLowerCase();
      if (
        host !== "youtube.com" &&
        !host.endsWith(".youtube.com") &&
        host !== "youtu.be"
      )
        return null;
      address.searchParams.set("t", String(Math.floor(seconds)) + "s");
      return address.href;
    } catch {
      return null;
    }
  };
  const captionMessage: Record<YouTubeView["caption_status"], string> = {
    retrieved: "Caption text retrieved from the video source.",
    unavailable: "No captions were available from the video source.",
    unsupported_format_or_language:
      "Captions exist, but no supported English caption format was available.",
    read_failed: "The caption read failed; no transcript text is shown.",
  };
  if (!metadata && youtube.evidence_expired)
    return (
      <section className="youtube-evidence" aria-label="YouTube evidence">
        <h5>YouTube evidence expired</h5>
        <p>Public metadata and caption previews are no longer available.</p>
      </section>
    );
  if (!metadata && youtube.caption_status === "unavailable") return null;
  return (
    <section className="youtube-evidence" aria-label="YouTube evidence">
      <h5>{metadata ? "Public video metadata" : "YouTube source read"}</h5>
      <p className="candidate-meta">
        These are public video counters, not private YouTube Analytics. The
        video’s creator identity is unknown; a video is not a verified creator
        lead.
      </p>
      {metadata && (
        <dl>
          {metadata.channel && (
            <div>
              <dt>Channel label</dt>
              <dd>{metadata.channel}</dd>
            </div>
          )}
          {metadata.published_on && (
            <div>
              <dt>Published</dt>
              <dd>
                <time dateTime={metadata.published_on}>
                  {metadata.published_on}
                </time>
              </dd>
            </div>
          )}
          {metadata.duration_seconds != null && (
            <div>
              <dt>Duration</dt>
              <dd>
                {Math.floor(metadata.duration_seconds / 60)}:
                {String(Math.floor(metadata.duration_seconds % 60)).padStart(
                  2,
                  "0",
                )}
              </dd>
            </div>
          )}
          {metadata.view_count != null && (
            <div>
              <dt>Public views when observed</dt>
              <dd>{metadata.view_count.toLocaleString()}</dd>
            </div>
          )}
          {metadata.like_count != null && (
            <div>
              <dt>Public likes when observed</dt>
              <dd>{metadata.like_count.toLocaleString()}</dd>
            </div>
          )}
          <div>
            <dt>Observed</dt>
            <dd>
              <time dateTime={metadata.observed_at}>
                {new Date(metadata.observed_at).toLocaleString()}
              </time>
            </dd>
          </div>
        </dl>
      )}
      {metadata?.description && (
        <details>
          <summary>Public video description</summary>
          <p className="candidate-snippet">{metadata.description}</p>
        </details>
      )}
      {metadata?.transcript_languages.length ? (
        <p className="candidate-meta">
          Caption languages listed by the source:{" "}
          {metadata.transcript_languages.join(", ")}.
        </p>
      ) : null}
      <p className="candidate-meta">{captionMessage[youtube.caption_status]}</p>
      {youtube.caption_status === "retrieved" && (
        <>
          <p className="candidate-meta">
            {youtube.caption_origin === "platform_automatic"
              ? "Platform-generated captions"
              : "Provided captions"}{" "}
            · {youtube.caption_language}
          </p>
          {youtube.segments.length > 0 && (
            <ol className="youtube-captions">
              {youtube.segments.map((segment) => {
                const source = timestampedUrl(segment.start_seconds);
                return (
                  <li key={segment.evidence_id}>
                    <p>
                      {source ? (
                        <a
                          href={source}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {segment.start_seconds.toFixed(1)}s–
                          {segment.end_seconds.toFixed(1)}s
                        </a>
                      ) : (
                        <span>
                          {segment.start_seconds.toFixed(1)}s–
                          {segment.end_seconds.toFixed(1)}s
                        </span>
                      )}
                    </p>
                    <blockquote>{segment.text}</blockquote>
                    {workspaceId ? (
                      <CriterionEvidence
                        api={api}
                        jobId={jobId}
                        workspaceId={workspaceId}
                        evidenceId={segment.evidence_id}
                      />
                    ) : (
                      <p className="candidate-meta">
                        Scoped citation unavailable.
                      </p>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
        </>
      )}
      {youtube.omitted_segments > 0 && (
        <p className="candidate-meta">
          {youtube.omitted_segments} caption cue
          {youtube.omitted_segments === 1 ? " was" : "s were"} omitted from this
          preview.
        </p>
      )}
      {youtube.evidence_expired && (
        <p className="candidate-meta">
          Some caption evidence has expired and is hidden.
        </p>
      )}
      {youtube.metadata_truncated && (
        <p className="candidate-meta">Some public metadata was shortened.</p>
      )}
    </section>
  );
}

export function ResearchResultsPanel({
  api,
  job,
  onExpanded,
  onClarification,
}: {
  api: ReturnType<typeof createApi>;
  job: ResearchJob;
  onExpanded?: (job: ResearchJob, prompt: string) => void;
  onClarification?: (job: ResearchJob) => void;
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
        {run?.stage && !finished.has(state) && (
          <p>Current stage: {run.stage.replaceAll("_", " ")}</p>
        )}
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
              {plan.status === "clarification_required" && job.workspace_id && (
                <ClarificationResponse
                  api={api}
                  jobId={job.id}
                  workspaceId={job.workspace_id}
                  question={
                    plan.interpretation.clarification ??
                    "Please clarify your research objective."
                  }
                  onStarted={onClarification}
                />
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
        <IdentityReviewPanel
          api={api}
          workspaceId={job.workspace_id}
          onReviewed={() => setRetry((value) => value + 1)}
        />
      )}
      {job.workspace_id && plan?.plan_id && (
        <SavedListsPanel
          api={api}
          workspaceId={job.workspace_id}
          planId={plan.plan_id}
          candidates={results?.results ?? []}
        />
      )}
      {job.workspace_id && plan?.plan_id && results?.groups && (
        <CrmDeliveryPanel
          api={api}
          workspaceId={job.workspace_id}
          planId={plan.plan_id}
          candidates={results.results}
          confirmed={results.groups.confirmed}
          near={results.groups.near_match}
        />
      )}
      {job.workspace_id && finished.has(state) && (
        <ResearchExpansion
          api={api}
          sourceJobId={job.id}
          workspaceId={job.workspace_id}
          onStarted={onExpanded}
        />
      )}
      {job.workspace_id && (state === "completed" || state === "partial") && (
        <ResearchRefinement
          api={api}
          sourceJobId={job.id}
          workspaceId={job.workspace_id}
          onStarted={onExpanded}
        />
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
                            {metric.queue_wait_samples > 0 && (
                              <span>
                                {metric.queue_wait_seconds} seconds queue wait (
                                {metric.queue_wait_samples} sample
                                {metric.queue_wait_samples === 1 ? "" : "s"})
                              </span>
                            )}
                            {metric.collection_timings && (
                              <span>
                                {(["network", "parser", "browser"] as const)
                                  .map((component) => {
                                    const seconds =
                                      metric.collection_timings?.[
                                        `${component}_seconds`
                                      ];
                                    const samples =
                                      metric.collection_timings?.[
                                        `${component}_samples`
                                      ] ?? 0;
                                    return `${component[0].toUpperCase()}${component.slice(1)} ${seconds === null ? "timing unavailable" : `${seconds}s`} (${samples} sample${samples === 1 ? "" : "s"})`;
                                  })
                                  .join(" · ")}
                              </span>
                            )}
                            {Object.entries(metric.outcomes)
                              .filter(([outcome]) => outcome !== "succeeded")
                              .map(([outcome, count]) => (
                                <span key={outcome}>
                                  {outcome.replaceAll("_", " ")}: {count} of{" "}
                                  {metric.observations} attempts
                                </span>
                              ))}
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
          <p role="status">
            {results?.resume_status === "available"
              ? "Saved results are available. The service confirmed this run can resume within its remaining limits."
              : results?.resume_status === "requires_reconciliation"
                ? "This run needs review before it can resume. Its saved results remain available."
                : results?.resume_status === "deadline_expired"
                  ? "The time limit for this run has passed. Its saved results remain available; start a new run to continue."
                  : results?.resume_status === "budget_exhausted"
                    ? "This run has reached its budget. Its saved results remain available; start a new run to continue."
                    : results?.resume_status === "new_prompt_required"
                      ? "This request needs a corrected prompt before it can continue. Its saved results remain available."
                      : "Resume availability cannot be confirmed yet. Your saved results remain available; check the run again before continuing."}
          </p>
          {results?.resume_status === "available" && (
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
          )}
          <button
            className="text-button"
            type="button"
            disabled={resuming}
            onClick={() => setRetry((value) => value + 1)}
          >
            Check run again <RefreshCw size={13} aria-hidden="true" />
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
          {results.groups && (
            <section
              className="qualification-groups"
              aria-labelledby="qualification-groups-title"
            >
              <h4 id="qualification-groups-title">
                Current qualification groups
              </h4>
              <p className="candidate-meta">
                Groups use reviewed facts and are recalculated from evidence
                still retained for this run. Indexed search references remain
                unverified.
              </p>
              {(
                [
                  ["confirmed", "Meets required criteria"],
                  ["near_match", "Needs review"],
                  ["excluded", "Excluded by a criterion"],
                  ["unverified", "Search reference only"],
                ] as const
              ).map(([group, heading]) => {
                const members = results.groups?.[group] ?? [];
                if (members.length === 0) return null;
                const byId = new Map(
                  results.results.map((candidate) => [candidate.id, candidate]),
                );
                return (
                  <details key={group}>
                    <summary>
                      {heading} ({members.length})
                    </summary>
                    <ul>
                      {members.map((id) => {
                        const candidate = byId.get(id);
                        return candidate ? (
                          <li key={id}>
                            <a href={`#result-${id}`}>
                              {candidate.title || candidate.url}
                            </a>
                          </li>
                        ) : null;
                      })}
                    </ul>
                  </details>
                );
              })}
            </section>
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
                  <li id={`result-${candidate.id}`} key={candidate.id}>
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
                    <CandidateFit
                      api={api}
                      jobId={job.id}
                      workspaceId={job.workspace_id}
                      candidate={candidate}
                    />
                    {job.workspace_id && finished.has(state) && (
                      <FollowupPanel
                        api={api}
                        sourceJobId={job.id}
                        workspaceId={job.workspace_id}
                        candidate={candidate}
                      />
                    )}
                    <p className="candidate-meta">
                      Retrieved{" "}
                      <time dateTime={candidate.observed_at}>
                        {candidate.observed_at}
                      </time>
                    </p>
                    <p className="candidate-snippet">
                      {candidate.snippet || "No search snippet was provided."}
                    </p>
                    {candidate.platform_reference && (
                      <section
                        className="platform-reference-notice"
                        aria-label="Platform reference status"
                      >
                        <h5>
                          {candidate.platform_reference.source === "linkedin"
                            ? "LinkedIn"
                            : "Reddit"}{" "}
                          {candidate.platform_reference.resource_kind ===
                          "unknown"
                            ? "indexed reference"
                            : `${candidate.platform_reference.resource_kind} · indexed reference`}
                        </h5>
                        <p>
                          Found through the search index. A direct platform read
                          was not attempted, and the subject’s identity is
                          unverified.
                        </p>
                        {(candidate.platform_reference.resource_kind ===
                          "post" ||
                          candidate.platform_reference.resource_kind ===
                            "comment") && (
                          <p className="candidate-meta">
                            The author is unknown; this reference does not name
                            a person lead.
                          </p>
                        )}
                      </section>
                    )}
                    {candidate.youtube && (
                      <YouTubeEvidence
                        api={api}
                        jobId={job.id}
                        workspaceId={job.workspace_id}
                        youtube={candidate.youtube}
                      />
                    )}
                    {candidate.discussion && !candidate.platform_reference && (
                      <section aria-label="Discussion reference">
                        <h5>
                          Discussion {candidate.discussion.resource_kind}{" "}
                          reference
                        </h5>
                        <p>
                          This is an indexed discussion reference. Its author
                          identity is unknown; the author is not a named lead.
                        </p>
                        <p className="candidate-meta">
                          The discussion body has not been verified by this
                          reference. Collection and source observations below
                          show any separate page read.
                        </p>
                      </section>
                    )}
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
                      <div className="candidate-meta">
                        <p>
                          {candidate.collection.status === "read"
                            ? candidate.source === "rss"
                              ? "Feed read"
                              : candidate.source === "github"
                                ? "Public metadata read"
                                : "Page read"
                            : "Source read unavailable"}
                          {candidate.collection.failure_code
                            ? ` · ${candidate.collection.failure_code.replaceAll("_", " ")}`
                            : ""}
                        </p>
                        {(
                          [
                            ["Network", candidate.collection.network_seconds],
                            ["Parser", candidate.collection.parser_seconds],
                            ["Browser", candidate.collection.browser_seconds],
                          ] as const
                        ).some(
                          ([, seconds]) => typeof seconds === "number",
                        ) && (
                          <p>
                            {(
                              [
                                [
                                  "Network",
                                  candidate.collection.network_seconds,
                                ],
                                ["Parser", candidate.collection.parser_seconds],
                                [
                                  "Browser",
                                  candidate.collection.browser_seconds,
                                ],
                              ] as const
                            )
                              .filter(
                                ([, seconds]) => typeof seconds === "number",
                              )
                              .map(
                                ([name, seconds]) =>
                                  `${name} ${typeof seconds === "number" ? seconds.toFixed(2) : ""}s`,
                              )
                              .join(" · ")}
                          </p>
                        )}
                      </div>
                    )}
                    {candidate.feed && (
                      <details className="candidate-provenance">
                        <summary>
                          Feed entries ({candidate.feed.entries.length}) ·
                          Unverified
                        </summary>
                        {candidate.feed.evidence_expired ? (
                          <p>
                            Feed evidence expired. Start a new run to refresh
                            it.
                          </p>
                        ) : candidate.feed.entries.length === 0 ? (
                          <p>No eligible feed entries were retained.</p>
                        ) : (
                          <ol>
                            {candidate.feed.entries.map((entry) => {
                              const address = safeSourceUrl(entry.url);
                              return (
                                <li key={entry.entry_id}>
                                  {address ? (
                                    <a
                                      href={address}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                    >
                                      {entry.title || entry.url}
                                    </a>
                                  ) : (
                                    <strong>
                                      {entry.title || "Feed entry"}
                                    </strong>
                                  )}
                                  <p className="candidate-meta">
                                    {entry.published_at ? (
                                      <>
                                        Published{" "}
                                        <time dateTime={entry.published_at}>
                                          {new Date(
                                            entry.published_at,
                                          ).toLocaleString()}
                                        </time>
                                      </>
                                    ) : (
                                      "Publication date not provided"
                                    )}
                                    {entry.updated_at && (
                                      <>
                                        {" "}
                                        · Updated{" "}
                                        <time dateTime={entry.updated_at}>
                                          {new Date(
                                            entry.updated_at,
                                          ).toLocaleString()}
                                        </time>
                                      </>
                                    )}
                                  </p>
                                  {entry.summary && <p>{entry.summary}</p>}
                                  {entry.summary_truncated && (
                                    <p className="candidate-meta">
                                      Summary shortened for this view.
                                    </p>
                                  )}
                                </li>
                              );
                            })}
                          </ol>
                        )}
                        {(candidate.feed.duplicate_count > 0 ||
                          candidate.feed.invalid_link_count > 0 ||
                          candidate.feed.omitted_entry_count > 0) && (
                          <p className="candidate-meta">
                            {candidate.feed.duplicate_count} repeated entries
                            omitted · {candidate.feed.invalid_link_count} unsafe
                            links omitted · {candidate.feed.omitted_entry_count}{" "}
                            entries outside this run’s limit.
                          </p>
                        )}
                      </details>
                    )}
                    {candidate.extraction && (
                      <details className="candidate-provenance">
                        <summary>
                          Source observations (
                          {candidate.extraction.observations.length}) ·
                          Unverified
                        </summary>
                        <p className="candidate-meta">
                          Quotes come from the saved source. Subject identity
                          and qualification still need verification.
                        </p>
                        {candidate.extraction.observations.length === 0 && (
                          <p>No supported observations were extracted.</p>
                        )}
                        {(() => {
                          const conflicts = new Map<
                            string,
                            typeof candidate.extraction.observations
                          >();
                          for (const observation of candidate.extraction
                            .observations) {
                            if (observation.status !== "conflict") continue;
                            const rows = conflicts.get(observation.field) ?? [];
                            rows.push(observation);
                            conflicts.set(observation.field, rows);
                          }
                          return conflicts.size > 0 ? (
                            <section aria-label="Conflicting source observations">
                              <h4>Conflicting source observations</h4>
                              <p className="candidate-meta">
                                Sources disagree on these fields. No value has
                                been selected as correct.
                              </p>
                              <ul>
                                {[...conflicts].map(([field, observations]) => (
                                  <li key={field}>
                                    <strong>
                                      {field.replaceAll("_", " ")}
                                    </strong>
                                    <ul>
                                      {observations.map((fact) => (
                                        <li key={fact.claim_id}>
                                          <strong>{String(fact.value)}</strong>
                                          <blockquote>{fact.quote}</blockquote>
                                          {(fact.evidence_ids ?? []).map(
                                            (evidenceId) => (
                                              <CriterionEvidence
                                                key={`${job.id}:${evidenceId}`}
                                                api={api}
                                                jobId={job.id}
                                                workspaceId={job.workspace_id}
                                                evidenceId={evidenceId}
                                              />
                                            ),
                                          )}
                                        </li>
                                      ))}
                                    </ul>
                                  </li>
                                ))}
                              </ul>
                            </section>
                          ) : null;
                        })()}
                        <ol>
                          {candidate.extraction.observations
                            .filter((fact) => fact.status !== "conflict")
                            .map((fact) => (
                              <li key={fact.claim_id}>
                                <strong>
                                  {fact.field.replaceAll("_", " ")}:{" "}
                                  {String(fact.value)}
                                </strong>
                                <p className="candidate-meta">
                                  {fact.status === "accepted"
                                    ? "Verified source fact · Candidate fit pending"
                                    : "Source observation · Unverified"}
                                </p>
                                <blockquote>{fact.quote}</blockquote>
                                {(fact.evidence_ids ?? []).map((evidenceId) => (
                                  <CriterionEvidence
                                    key={`${job.id}:${evidenceId}`}
                                    api={api}
                                    jobId={job.id}
                                    workspaceId={job.workspace_id}
                                    evidenceId={evidenceId}
                                  />
                                ))}
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
