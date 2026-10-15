"use client";

import { useState } from "react";
import type { createApi, ResearchJob } from "../lib/api";

export function ClarificationResponse({
  api,
  jobId,
  workspaceId,
  question,
  onStarted,
}: {
  api: ReturnType<typeof createApi>;
  jobId: string;
  workspaceId: string;
  question: string;
  onStarted?: (job: ResearchJob) => void;
}) {
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onStarted?.(await api.answerClarification(jobId, workspaceId, answer));
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "The clarification could not be submitted.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      className="run-recovery clarification-response"
      onSubmit={(event) => void submit(event)}
    >
      <p>{question}</p>
      <label htmlFor={`clarification-${jobId}`}>Your answer</label>
      <textarea
        id={`clarification-${jobId}`}
        value={answer}
        onChange={(event) => setAnswer(event.target.value)}
        maxLength={500}
        rows={2}
        disabled={busy}
      />
      <p className="candidate-meta">
        Your original prompt and this answer will be used together to create a
        new plan revision. The existing run and its results remain saved.
      </p>
      <button
        className="text-button"
        type="submit"
        disabled={busy || !answer.trim()}
      >
        {busy ? "Updating the plan…" : "Answer and continue"}
      </button>
      {error && <p role="alert">{error}</p>}
    </form>
  );
}
