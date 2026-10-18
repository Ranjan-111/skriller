"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ExternalLink, RefreshCw } from "lucide-react";
import {
  ApiError,
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
  type ConnectionMetadata,
  type RebindOptions,
  type RebindSelection,
  type RedditThreadView,
  type LinkedInReadView,
  type SocialReadView,
  type YouTubeView,
  type RoleReviewInput,
  type RoleReviewView,
} from "../lib/api";

import { SourceMarkdown } from "./source-markdown";
import { downloadSources, SOURCE_EXPORT_LIMIT } from "../lib/exports";
import { QualifiedExportPanel } from "./qualified-export-panel";
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

function CheckpointRebindPanel({
  api,
  jobId,
  workspaceId,
  onResumed,
}: {
  api: ReturnType<typeof createApi>;
  jobId: string;
  workspaceId: string;
  onResumed: () => void;
}) {
  const [options, setOptions] = useState<RebindOptions | null>(null);
  const [connections, setConnections] = useState<ConnectionMetadata[]>([]);
  const [source, setSource] = useState<"linkedin" | "reddit" | "">("");
  const [replacement, setReplacement] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const retryRequest = useRef<{
    selection: RebindSelection;
    key: string;
  } | null>(null);

  async function loadChoices() {
    setLoading(true);
    setError("");
    setSuccess("");
    try {
      const [savedOptions, metadata] = await Promise.all([
        api.rebindOptions(jobId, workspaceId),
        api.connections(workspaceId),
      ]);
      setOptions(savedOptions);
      setConnections(metadata);
      setSource("");
      setReplacement("");
      setConfirmed(false);
      retryRequest.current = null;
      if (savedOptions.options.length === 0)
        setError(
          "No supported pending connection replacement is available. Keep these results and start a new run or ask an owner to review the checkpoint.",
        );
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Connection choices could not be verified. Saved results remain available.",
      );
    } finally {
      setLoading(false);
    }
  }

  const sourceOption = options?.options.find((item) => item.source === source);
  const replacementChoices = connections.filter(
    (item) =>
      !!sourceOption &&
      item.source === sourceOption.source &&
      item.state === "active" &&
      Date.parse(item.expires_at) > Date.now() &&
      item.scopes.includes("read") &&
      (item.source !== "linkedin" || item.auth_kind === "session") &&
      (item.source !== "reddit" || item.auth_kind === "oauth") &&
      item.id !== sourceOption.previous_connection_ref,
  );

  async function submit() {
    if (!sourceOption || !replacement || !confirmed) return;
    if (!retryRequest.current) {
      retryRequest.current = {
        key: globalThis.crypto.randomUUID(),
        selection: {
          source: sourceOption.source,
          entity_ids: [...sourceOption.entity_ids],
          expected_job_version: options!.job_version,
          previous_connection_ref: sourceOption.previous_connection_ref,
          replacement_connection_ref: replacement,
        },
      };
    }
    setSubmitting(true);
    setError("");
    setSuccess("");
    try {
      const snapshot = await api.rebindAndResume(
        jobId,
        workspaceId,
        retryRequest.current.selection,
        retryRequest.current.key,
      );
      retryRequest.current = null;
      setSuccess(
        `Replacement confirmed. The run is ${snapshot.state.replaceAll("_", " ")}.`,
      );
      onResumed();
    } catch (failure) {
      const status =
        failure && typeof failure === "object" && "status" in failure
          ? Number(failure.status)
          : undefined;
      if (status === 409) {
        retryRequest.current = null;
        setOptions(null);
        setConfirmed(false);
        setError(
          "The checkpoint changed. Review the current choices and confirm again before retrying.",
        );
      } else {
        setError(
          failure instanceof Error
            ? `${failure.message} You can retry the same confirmed request safely.`
            : "The replacement was not confirmed. Retry the same confirmed request or check the run.",
        );
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <details className="candidate-provenance checkpoint-rebind">
      <summary>Replace source access for pending reads</summary>
      <p className="candidate-meta">
        This owner-only action changes access for the listed, undispatched
        LinkedIn or Reddit reads and resumes this existing run. It does not
        validate provider authorization. Your saved results stay available.
      </p>
      {!options && (
        <button
          className="text-button"
          type="button"
          disabled={loading}
          onClick={() => void loadChoices()}
        >
          {loading ? "Loading owner choices…" : "Review connection choices"}
        </button>
      )}
      {options && options.options.length > 0 && (
        <div>
          <label>
            Source to resume
            <select
              value={source}
              disabled={submitting}
              onChange={(event) => {
                setSource(event.target.value as "linkedin" | "reddit" | "");
                setReplacement("");
                setConfirmed(false);
                retryRequest.current = null;
              }}
            >
              <option value="">Choose a source</option>
              {options.options.map((item) => (
                <option key={item.source} value={item.source}>
                  {item.source === "linkedin" ? "LinkedIn" : "Reddit"} (
                  {item.entity_ids.length} pending read
                  {item.entity_ids.length === 1 ? "" : "s"})
                </option>
              ))}
            </select>
          </label>
          {sourceOption && (
            <label>
              Active replacement connection
              <select
                value={replacement}
                disabled={submitting}
                onChange={(event) => {
                  setReplacement(event.target.value);
                  setConfirmed(false);
                  retryRequest.current = null;
                }}
              >
                <option value="">Choose a connection</option>
                {replacementChoices.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.auth_kind} · expires{" "}
                    {new Date(item.expires_at).toLocaleDateString()}
                  </option>
                ))}
              </select>
              {replacementChoices.length === 0 && (
                <span role="status">
                  No other active connection is available for this source.
                </span>
              )}
            </label>
          )}
          {sourceOption && replacement && (
            <label className="candidate-meta">
              <input
                type="checkbox"
                checked={confirmed}
                disabled={submitting}
                onChange={(event) => {
                  setConfirmed(event.target.checked);
                  retryRequest.current = null;
                }}
              />
              I understand this replaces access for{" "}
              {sourceOption.entity_ids.length} pending {sourceOption.source}{" "}
              read{sourceOption.entity_ids.length === 1 ? "" : "s"} and resumes
              this run.
            </label>
          )}
          <button
            className="text-button"
            type="button"
            disabled={submitting || !sourceOption || !replacement || !confirmed}
            onClick={() => void submit()}
          >
            {submitting
              ? "Applying confirmed change…"
              : retryRequest.current
                ? "Retry same confirmed request"
                : "Replace access and resume"}
          </button>
        </div>
      )}
      {error && <p role="alert">{error}</p>}
      {success && <p role="status">{success}</p>}
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

const stageDescriptions: Record<string, string> = {
  planning: "Understanding your prompt and preparing the search.",
  discovering: "Searching your selected sources for matching references.",
  collecting: "Reading available source content.",
  extracting: "Organising the information found in sources.",
  qualifying: "Checking available evidence against your criteria.",
  ranking: "Ordering results by the evidence available.",
  reporting: "Preparing the research report from saved evidence.",
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

type RolePair = {
  role: string;
  date: string;
  evidence: string;
  value: string;
  dateValue: string;
  quote: string;
};
function rolePairs(candidate: ResearchCandidate): RolePair[] {
  const observations = candidate.extraction?.observations ?? [];
  const roles = observations.filter(
    (item) =>
      ["job_title", "current_role"].includes(item.field) &&
      typeof item.value === "string",
  );
  const dates = observations.filter(
    (item) =>
      item.field === "role_effective_date" &&
      typeof item.value === "string" &&
      /^\d{4}-\d{2}-\d{2}$/.test(item.value),
  );
  const pairs: RolePair[] = [];
  for (const role of roles)
    for (const date of dates) {
      const shared = (role.evidence_ids ?? []).filter((id) =>
        (date.evidence_ids ?? []).includes(id),
      );
      for (const evidence of shared)
        pairs.push({
          role: role.claim_id,
          date: date.claim_id,
          evidence,
          value: String(role.value),
          dateValue: String(date.value),
          quote: role.quote,
        });
    }
  return pairs.slice(0, 12);
}

export function OwnerRoleReview({
  api,
  workspaceId,
  candidate,
  onRefresh,
}: {
  api: ReturnType<typeof createApi>;
  workspaceId: string;
  candidate: ResearchCandidate;
  onRefresh: (signal?: AbortSignal) => Promise<void>;
}) {
  const profile =
    candidate.source === "linkedin" &&
    candidate.provider === "linkedin_mcp" &&
    candidate.linkedin_read?.resource.resource_kind === "profile";
  const pairs = profile ? rolePairs(candidate) : [];
  const [previousIndex, setPreviousIndex] = useState("");
  const [replacementIndex, setReplacementIndex] = useState("");
  const [preview, setPreview] = useState<RoleReviewView | null>(null);
  const [sameSubject, setSameSubject] = useState(false);
  const [personSubject, setPersonSubject] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const operations = useRef<AbortController | null>(null);
  const pending = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    operations.current = controller;
    pending.current = false;
    setPreviousIndex("");
    setReplacementIndex("");
    setPreview(null);
    setSameSubject(false);
    setPersonSubject(false);
    setBusy(false);
    setError("");
    setSuccess("");
    return () => controller.abort();
  }, [api, candidate, workspaceId]);
  if (!profile || pairs.length < 2) return null;
  const makeReference = (index: string): RoleReviewInput["previous"] | null => {
    if (!/^(0|[1-9]\d*)$/.test(index)) return null;
    const pair = pairs[Number(index)];
    return pair
      ? {
          role_claim_id: pair.role,
          date_claim_id: pair.date,
          evidence_id: pair.evidence,
        }
      : null;
  };
  const selectedPrevious = makeReference(previousIndex);
  const selectedReplacement = makeReference(replacementIndex);
  async function loadPreview() {
    const controller = operations.current;
    if (
      !controller ||
      controller.signal.aborted ||
      pending.current ||
      !selectedPrevious ||
      !selectedReplacement ||
      previousIndex === replacementIndex
    )
      return;
    pending.current = true;
    setBusy(true);
    setError("");
    setSuccess("");
    setPreview(null);
    setSameSubject(false);
    setPersonSubject(false);
    try {
      const value = await api.previewRoleReview(
        workspaceId,
        {
          entity_id: candidate.id,
          previous: selectedPrevious,
          replacement: selectedReplacement,
        },
        candidate.url,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setPreview(value);
    } catch (failure) {
      if (controller.signal.aborted) return;
      setError(
        failure instanceof Error
          ? failure.message
          : "Unable to preview this role review.",
      );
      if (failure instanceof ApiError && failure.status === 409) {
        try {
          await onRefresh(controller.signal);
        } catch {
          /* Retain visible results. */
        }
      }
    } finally {
      if (!controller.signal.aborted) {
        pending.current = false;
        setBusy(false);
      }
    }
  }
  async function approve() {
    const controller = operations.current;
    if (
      !controller ||
      controller.signal.aborted ||
      pending.current ||
      !preview ||
      !selectedPrevious ||
      !selectedReplacement ||
      !sameSubject ||
      (preview.requires_person_confirmation && !personSubject)
    )
      return;
    pending.current = true;
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await api.approveRoleReview(
        workspaceId,
        {
          entity_id: candidate.id,
          previous: selectedPrevious,
          replacement: selectedReplacement,
          expected_review_hash: preview.review_hash,
          same_subject_confirmed: true,
          person_subject_confirmed: preview.requires_person_confirmation
            ? true
            : false,
        },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setPreview(null);
      setSameSubject(false);
      setPersonSubject(false);
      await onRefresh(controller.signal);
      if (controller.signal.aborted) return;
      setSuccess(
        "Role chronology reviewed. Current fit and saved evidence have been refreshed.",
      );
    } catch (failure) {
      if (controller.signal.aborted) return;
      const message =
        failure instanceof Error
          ? failure.message
          : "The role review response was unclear. Check current results before continuing.";
      setError(message + " Load a fresh preview before confirming again.");
      // A conflict or lost/invalid response may follow a committed classification. Never replay its old review hash.
      setPreview(null);
      setSameSubject(false);
      setPersonSubject(false);
      if (!(failure instanceof ApiError && failure.status === 403)) {
        try {
          await onRefresh(controller.signal);
        } catch {
          /* Keep current result details visible if refresh fails. */
        }
      }
    } finally {
      if (!controller.signal.aborted) {
        pending.current = false;
        setBusy(false);
      }
    }
  }
  const prior = preview?.previous;
  const replacement = preview?.replacement;
  return (
    <details className="candidate-provenance owner-role-review">
      <summary>Review saved LinkedIn role chronology</summary>
      <p className="candidate-meta">
        Choose two existing role and date observations from this saved profile.
        They remain unverified until you review the exact source evidence. This
        does not verify identity or link other platforms.
      </p>
      <label>
        Earlier role and date{" "}
        <select
          aria-label="Earlier role and date"
          value={previousIndex}
          disabled={busy}
          onChange={(event) => {
            setPreviousIndex(event.target.value);
            setPreview(null);
          }}
        >
          <option value="">Choose an observation</option>
          {pairs.map((pair, index) => (
            <option
              value={index}
              key={`${pair.role}:${pair.date}:${pair.evidence}:earlier`}
            >
              {pair.value} · {pair.dateValue} · {pair.quote.slice(0, 100)}
            </option>
          ))}
        </select>
      </label>
      <label>
        Later role and date{" "}
        <select
          aria-label="Later role and date"
          value={replacementIndex}
          disabled={busy}
          onChange={(event) => {
            setReplacementIndex(event.target.value);
            setPreview(null);
          }}
        >
          <option value="">Choose an observation</option>
          {pairs.map((pair, index) => (
            <option
              value={index}
              key={`${pair.role}:${pair.date}:${pair.evidence}:later`}
            >
              {pair.value} · {pair.dateValue} · {pair.quote.slice(0, 100)}
            </option>
          ))}
        </select>
      </label>
      <button
        className="text-button"
        type="button"
        disabled={
          busy ||
          !selectedPrevious ||
          !selectedReplacement ||
          previousIndex === replacementIndex
        }
        onClick={() => void loadPreview()}
      >
        {busy ? "Loading review…" : "Preview role change"}
      </button>
      {preview && prior && replacement && (
        <section aria-label="Role review preview">
          <h5>
            {preview.subject_name || candidate.title} · saved profile role
            chronology
          </h5>
          {[prior, replacement].map((source, index) => (
            <blockquote key={source.role_claim_id}>
              <strong>
                {index === 0 ? "Earlier" : "Later"}: {source.role} ·{" "}
                {source.effective_date}
              </strong>
              <p>{source.excerpt}</p>
              <a
                href={safeSourceUrl(source.source_url) ?? undefined}
                target="_blank"
                rel="noopener noreferrer"
              >
                Open saved source
              </a>
            </blockquote>
          ))}
          <label>
            <input
              type="checkbox"
              checked={sameSubject}
              onChange={(event) => setSameSubject(event.target.checked)}
            />{" "}
            I reviewed this evidence and confirm both roles describe the same
            subject.
          </label>
          {preview.requires_person_confirmation && (
            <label>
              <input
                type="checkbox"
                checked={personSubject}
                onChange={(event) => setPersonSubject(event.target.checked)}
              />{" "}
              I separately confirm the original LinkedIn profile represents a
              person.
            </label>
          )}
          <p className="candidate-meta">
            The source identity remains unverified; role review does not
            validate the profile owner, contact details, or intent.
          </p>
          <button
            className="text-button"
            type="button"
            disabled={
              busy ||
              !sameSubject ||
              (preview.requires_person_confirmation && !personSubject)
            }
            onClick={() => void approve()}
          >
            {busy ? "Applying reviewed change…" : "Confirm role chronology"}
          </button>
        </section>
      )}
      {error && <p role="alert">{error}</p>}
      {success && <p role="status">{success}</p>}
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

function RedditThreadEvidence({ view }: { view: RedditThreadView }) {
  const { thread } = view;
  const parentDepth = new Map<string, number>([[thread.post.native_id, 0]]);
  const commentDepth = thread.comments.map((comment) => {
    const depth = Math.min((parentDepth.get(comment.parent_id) ?? 0) + 1, 6);
    parentDepth.set(comment.native_id, depth);
    return depth;
  });
  const formatDate = (date: string | null) =>
    date ? new Date(date).toLocaleString() : "Date unavailable";
  const postUrl = safeSourceUrl(thread.post.source_url);

  return (
    <details className="reddit-thread-evidence candidate-provenance">
      <summary>
        Reddit post and comments ({thread.comments.length} retained)
      </summary>
      <p className="candidate-meta">
        Directly read public thread content. Handles are unverified; this
        evidence does not establish a person, company, buyer, or buying intent.
      </p>
      <section aria-label="Reddit post">
        <h5>
          {postUrl ? (
            <a href={postUrl} target="_blank" rel="noopener noreferrer">
              {thread.post.title || "Untitled Reddit post"}
              <ExternalLink size={14} aria-hidden="true" />
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
          ) : (
            thread.post.title || "Untitled Reddit post"
          )}
        </h5>
        <p className="candidate-meta">
          r/{thread.post.subreddit} · u/
          {thread.post.author_handle ?? "author unavailable"} ·{" "}
          {formatDate(thread.post.published_at)}
        </p>
        {thread.post.content_unavailable ? (
          <p className="reddit-unavailable">
            Post text unavailable (deleted or removed).
          </p>
        ) : (
          <p className="reddit-body">
            {thread.post.excerpt || "No post text was retained."}
            {thread.post.truncated ? "… (post excerpt shortened)" : ""}
          </p>
        )}
      </section>
      {view.signals && view.signals.length > 0 && (
        <section aria-label="Quoted problem signals">
          <h5>Quoted problem signals</h5>
          <p className="candidate-meta">
            These exact quotes are source-specific and unverified. They do not
            indicate buying intent.
          </p>
          <ul>
            {view.signals.map((signal, index) => (
              <li key={`${signal.resource_id}:${index}`}>
                <blockquote className="reddit-quote">
                  <p>{signal.quote}</p>
                  <footer>
                    {signal.resource_id} · {formatDate(signal.published_at)} ·{" "}
                    <a
                      href={safeSourceUrl(signal.source_url) ?? undefined}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      Open quoted source
                    </a>
                  </footer>
                </blockquote>
              </li>
            ))}
          </ul>
        </section>
      )}
      {thread.comments.length > 0 && (
        <section aria-label="Reddit comments">
          <h5>Comments</h5>
          <ol className="reddit-comments">
            {thread.comments.map((comment, index) => (
              <li
                key={comment.native_id}
                style={{
                  marginInlineStart: `${Math.max(0, commentDepth[index] - 1) * 12}px`,
                }}
              >
                <p className="candidate-meta">
                  {comment.author_handle
                    ? `u/${comment.author_handle} · handle not verified`
                    : "Author unavailable"}{" "}
                  · {formatDate(comment.published_at)} · replies to{" "}
                  {comment.parent_id}
                </p>
                {comment.content_unavailable ? (
                  <p className="reddit-unavailable">
                    Comment text unavailable (deleted or removed).
                  </p>
                ) : (
                  <p className="reddit-body">
                    {comment.text || "No comment text was retained."}
                    {comment.truncated ? "… (comment shortened)" : ""}
                  </p>
                )}
                <a
                  href={safeSourceUrl(comment.source_url) ?? undefined}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Open comment
                </a>
              </li>
            ))}
          </ol>
        </section>
      )}
      {(thread.omitted_comments > 0 ||
        thread.unexpanded_nodes > 0 ||
        !thread.coverage_complete) && (
        <p className="candidate-meta" role="status">
          Partial thread coverage: {thread.omitted_comments} comments omitted ·{" "}
          {thread.unexpanded_nodes} reply groups unexpanded.
        </p>
      )}
      {view.rejected_signals > 0 && (
        <p className="candidate-meta" role="status">
          {view.rejected_signals} unsupported quote
          {view.rejected_signals === 1 ? "" : "s"} omitted.
        </p>
      )}
      {view.signal_failure_code && (
        <p className="candidate-meta" role="status">
          Problem-signal extraction unavailable (
          {view.signal_failure_code.replaceAll("_", " ")}).
        </p>
      )}
    </details>
  );
}

function SocialReadEvidence({ view }: { view: SocialReadView }) {
  const { resource } = view;
  const instagram = resource.source === "instagram";
  return (
    <details className="reddit-thread-evidence candidate-provenance">
      <summary>
        {instagram
          ? "Instagram public profile read"
          : "Facebook profile header read"}
      </summary>
      <p className="candidate-meta">
        Collected {new Date(resource.observed_at).toLocaleString()}. Coverage is
        partial and the subject’s identity is unverified.
      </p>
      <p>{resource.name || resource.username}</p>
      {resource.source === "instagram" ? (
        <>
          <p className="reddit-body">
            {resource.bio_excerpt || "No biography excerpt available."}
          </p>
          <p className="candidate-meta">
            Followers: {resource.followers ?? "Unknown"} · Following:{" "}
            {resource.following ?? "Unknown"} · Posts:{" "}
            {resource.posts ?? "Unknown"}
          </p>
          <p className="candidate-meta">
            Account type is unknown. Owner analytics are unavailable.
          </p>
        </>
      ) : (
        <>
          <p className="candidate-meta">
            Followers shown: {resource.followers_display ?? "Unknown"} · Friends
            shown: {resource.friends_display ?? "Unknown"}
          </p>
          <p className="candidate-meta">
            Visibility and company identity are unknown. Group access is
            unavailable. Displayed counts retain the source’s wording.
          </p>
        </>
      )}
    </details>
  );
}

function LinkedInReadEvidence({ view }: { view: LinkedInReadView }) {
  const { resource } = view;
  const sourceUrl = safeSourceUrl(resource.source_url);
  const resourceLabel =
    resource.resource_kind === "profile"
      ? "Profile section"
      : resource.resource_kind === "company"
        ? "Company overview"
        : "Post";
  return (
    <details className="reddit-thread-evidence candidate-provenance">
      <summary>LinkedIn {resourceLabel.toLowerCase()} read</summary>
      <p className="candidate-meta">
        This is source text from one section. Coverage is partial; the subject’s
        identity is unknown, contact details are unavailable, and buying intent
        was not inferred.
      </p>
      <p className="candidate-meta">
        Collected {new Date(resource.observed_at).toLocaleString()} ·{" "}
        {resource.section.replaceAll("_", " ")}
      </p>
      <p className="reddit-body">
        {resource.text}
        {resource.text_truncated ? "… (section text shortened)" : ""}
      </p>
      {sourceUrl && (
        <p className="candidate-meta">
          <a href={sourceUrl} target="_blank" rel="noopener noreferrer">
            Open the LinkedIn source{" "}
            <ExternalLink size={13} aria-hidden="true" />
            <span className="sr-only"> (opens in a new tab)</span>
          </a>
        </p>
      )}
    </details>
  );
}

export function ResearchResultsPanel({
  api,
  job,
  onExpanded,
  onClarification,
  onRedditRefresh,
  onEditPrompt,
}: {
  api: ReturnType<typeof createApi>;
  job: ResearchJob;
  onExpanded?: (job: ResearchJob, prompt: string) => void;
  onClarification?: (job: ResearchJob) => void;
  onRedditRefresh?: () => void;
  onEditPrompt?: () => void;
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
  const redditRefreshSent = useRef(false);
  const notifyRedditRefresh = useCallback(() => {
    if (redditRefreshSent.current) return;
    redditRefreshSent.current = true;
    onRedditRefresh?.();
  }, [onRedditRefresh]);
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
        if (finished.has(snapshot.state)) notifyRedditRefresh();
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
  }, [api, job.id, job.workspace_id, retry, notifyRedditRefresh]);

  useEffect(() => {
    redditRefreshSent.current = false;
  }, [job.id]);

  useEffect(() => {
    if (!job.workspace_id || finished.has(run?.state ?? job.status)) return;
    const controller = new AbortController();
    void (async () => {
      try {
        for await (const update of api.progressEvents(
          { job_id: job.id, workspace_id: job.workspace_id ?? "" },
          { signal: controller.signal },
        )) {
          if (controller.signal.aborted) return;
          const event = update.data;
          if (
            event.kind === "source_access_renewed" &&
            event.details.source === "reddit"
          ) {
            notifyRedditRefresh();
            return;
          }
        }
      } catch {
        // Status polling remains the fallback when progress streaming is unavailable.
      }
    })();
    return () => controller.abort();
  }, [
    api,
    job.id,
    job.workspace_id,
    job.status,
    run?.state,
    notifyRedditRefresh,
  ]);

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
  }, [api, job.id, job.workspace_id, run?.state]);

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
        {!finished.has(state) && (
          <div className="research-activity">
            <RefreshCw size={18} className="checking" aria-hidden="true" />
            <div>
              <strong>
                {run?.stage
                  ? `Current stage: ${run.stage.replaceAll("_", " ")}`
                  : "Waiting for the research worker"}
              </strong>
              <p>
                {run?.stage
                  ? (stageDescriptions[run.stage] ??
                    "Research is running. Results appear here as they become available.")
                  : "Your request is saved. Research will begin when a worker picks it up."}
              </p>
            </div>
          </div>
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
              {plan.status === "rejected" && plan.planning_failure && (
                <div className="notice planning-failure" role="alert">
                  <strong>
                    {plan.planning_failure.reason === "invalid_interpretation"
                      ? "This request could not be interpreted safely."
                      : plan.planning_failure.reason === "model_unavailable"
                        ? "The planning service is unavailable."
                        : plan.planning_failure.reason === "budget_exhausted"
                          ? "This run reached its planning limit."
                          : "This run stopped before planning could finish."}
                  </strong>
                  <p>
                    {plan.planning_failure.reason === "invalid_interpretation"
                      ? "Review the prompt and make the people, companies, or evidence you want more specific."
                      : plan.planning_failure.reason === "model_unavailable"
                        ? "Check that the configured planning service is ready before starting another run."
                        : plan.planning_failure.reason === "budget_exhausted"
                          ? "Review the workspace limits before deciding whether to start another run."
                          : "Review this run before deciding whether to start another one."}
                  </p>
                  <p>
                    Source search did not begin. Nothing will retry
                    automatically. Your original prompt is still in the
                    composer; edit it there and start a new run only when you
                    are ready.
                  </p>
                  {onEditPrompt && (
                    <button
                      className="text-button"
                      type="button"
                      onClick={onEditPrompt}
                    >
                      Edit original prompt
                    </button>
                  )}
                </div>
              )}
              {plan.status === "rejected" && !plan.planning_failure && (
                <div className="notice" role="status">
                  <strong>
                    This run did not produce a validated interpretation.
                  </strong>
                  <p>
                    Review the run, then edit the original prompt in the
                    composer before choosing whether to start another run.
                  </p>
                  {onEditPrompt && (
                    <button
                      className="text-button"
                      type="button"
                      onClick={onEditPrompt}
                    >
                      Edit original prompt
                    </button>
                  )}
                </div>
              )}
              {plan.status !== "rejected" && (
                <>
                  {plan.interpretation.clarification && (
                    <p className="notice" role="status">
                      {plan.interpretation.clarification}
                    </p>
                  )}
                  {plan.status === "clarification_required" &&
                    job.workspace_id && (
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
                  {(plan.interpretation.unsupported_criteria ?? []).length >
                    0 && (
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
        <QualifiedExportPanel
          api={api}
          workspaceId={job.workspace_id}
          planId={plan.plan_id}
          candidates={results.results}
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
          <CheckpointRebindPanel
            api={api}
            jobId={job.id}
            workspaceId={job.workspace_id}
            onResumed={() => setRetry((value) => value + 1)}
          />
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
      {results && (!error || results.results.length > 0) && (
        <>
          <h3>Discovered sources ({results.results.length})</h3>
          {results.results.length > 0 && (
            <div
              className="source-exports"
              aria-label="Download research sources"
            >
              <button
                className="text-button"
                type="button"
                onClick={() => downloadSources(results.results, "json")}
              >
                Download sources as JSON
              </button>
              <button
                className="text-button"
                type="button"
                onClick={() => downloadSources(results.results, "csv")}
              >
                Download sources as CSV
              </button>
              {results.results.length > SOURCE_EXPORT_LIMIT && (
                <p>
                  Downloads include the first {SOURCE_EXPORT_LIMIT} sources.
                </p>
              )}
            </div>
          )}
          <p>
            Source excerpts and indexed references are unverified. Check each
            original source before judging fit or using contact information.
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
                still retained for this run. A source excerpt alone does not
                verify a person, company, or qualification.
              </p>
              {(
                [
                  ["confirmed", "Meets required criteria"],
                  ["near_match", "Needs review"],
                  ["excluded", "Excluded by a criterion"],
                  ["unverified", "Unverified sources"],
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
              {state === "completed"
                ? "No matching sources were returned. Try a more specific prompt or different sources."
                : finished.has(state)
                  ? run?.terminal_reason === "source_interrupted"
                    ? "Source search was interrupted before any results could be saved. Try again later or check source readiness. This does not mean your prompt had no matches."
                    : "This run stopped before any sources were returned. Review the run status and source readiness before starting a new run."
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
                      {candidate.source} ·{" "}
                      {candidate.evidence_kind === "search_reference"
                        ? "Connected search reference"
                        : candidate.evidence_kind === "public_post"
                          ? "Public post excerpt"
                          : "Indexed search reference"}{" "}
                      · Unverified
                    </p>
                    <CandidateFit
                      api={api}
                      jobId={job.id}
                      workspaceId={job.workspace_id}
                      candidate={candidate}
                    />
                    {job.workspace_id && finished.has(state) && (
                      <OwnerRoleReview
                        key={`${job.workspace_id}:${job.id}:${candidate.id}`}
                        api={api}
                        workspaceId={job.workspace_id}
                        candidate={candidate}
                        onRefresh={async (signal) => {
                          const refreshed = await api.results(
                            job.id,
                            job.workspace_id,
                            signal,
                          );
                          if (!signal?.aborted) setResults(refreshed);
                        }}
                      />
                    )}
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
                    <div className="candidate-snippet">
                      <SourceMarkdown>
                        {candidate.snippet || "No source excerpt was provided."}
                      </SourceMarkdown>
                    </div>
                    {candidate.platform_reference && (
                      <section
                        className="platform-reference-notice"
                        aria-label="Platform reference status"
                      >
                        <h5>
                          {candidate.platform_reference.source === "linkedin"
                            ? "LinkedIn"
                            : candidate.platform_reference.source ===
                                "instagram"
                              ? "Instagram"
                              : candidate.platform_reference.source ===
                                  "facebook"
                                ? "Facebook"
                                : "Reddit"}{" "}
                          {candidate.platform_reference.access ===
                          "connected_search_reference_only"
                            ? "connected search reference"
                            : candidate.platform_reference.resource_kind ===
                                "unknown"
                              ? "indexed reference"
                              : `${candidate.platform_reference.resource_kind} · indexed reference`}
                        </h5>
                        <p>
                          {candidate.platform_reference.access ===
                          "connected_search_reference_only"
                            ? "Returned by connected platform search. This is a search reference; no profile or post was opened, and the subject’s identity is unverified."
                            : "Found through the search index. A direct platform read was not attempted, and the subject’s identity is unverified."}
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
                    {candidate.reddit_thread && (
                      <RedditThreadEvidence view={candidate.reddit_thread} />
                    )}
                    {candidate.social_read && (
                      <SocialReadEvidence view={candidate.social_read} />
                    )}
                    {candidate.linkedin_read && (
                      <LinkedInReadEvidence view={candidate.linkedin_read} />
                    )}
                    {!candidate.linkedin_read &&
                      candidate.source === "linkedin" &&
                      candidate.provider === "linkedin_mcp" &&
                      candidate.collection?.status === "read" && (
                        <p className="candidate-meta" role="note">
                          LinkedIn was read, but the retained section text has
                          expired or is unavailable.
                        </p>
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
