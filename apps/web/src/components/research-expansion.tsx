"use client";

import { useState } from "react";
import type { createApi, ResearchJob } from "../lib/api";

export function ResearchExpansion({
  api,
  sourceJobId,
  workspaceId,
  onStarted,
}: {
  api: ReturnType<typeof createApi>;
  sourceJobId: string;
  workspaceId: string;
  onStarted?: (job: ResearchJob, prompt: string) => void;
}) {
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [started, setStarted] = useState<ResearchJob | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const job = await api.expandResearch(sourceJobId, workspaceId, prompt);
      setStarted(job);
      onStarted?.(job, prompt.trim());
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Expanded research could not be started.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className="candidate-provenance research-expansion">
      <summary>Search further from this run</summary>
      <p className="candidate-meta">
        Describe what to search next. This starts a new bounded run using the
        current run’s approved source choices and counts toward your workspace
        allowance.
      </p>
      <form onSubmit={(event) => void submit(event)}>
        <label htmlFor={`expand-${sourceJobId}`} className="sr-only">
          Further research prompt
        </label>
        <textarea
          id={`expand-${sourceJobId}`}
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          maxLength={1500}
          rows={3}
          placeholder="What should the next search find?"
          disabled={busy}
        />
        <button
          type="submit"
          className="text-button"
          disabled={busy || prompt.trim().length < 3}
        >
          {busy ? "Starting research…" : "Start expanded research"}
        </button>
      </form>
      {error && <p role="alert">{error}</p>}
      {started && !onStarted && (
        <p role="status">New research run {started.id} started.</p>
      )}
    </details>
  );
}
