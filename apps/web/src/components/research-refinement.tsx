"use client";

import { useState } from "react";
import type { createApi, ResearchJob } from "../lib/api";

export function ResearchRefinement({
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

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const next = await api.refineResearch(sourceJobId, workspaceId, prompt);
      onStarted?.(next, prompt.trim());
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "The refinement could not be started.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className="candidate-provenance research-expansion">
      <summary>Refine this search</summary>
      <p className="candidate-meta">
        Describe a criterion to add, prefer, exclude, or explicitly relax. A new
        plan reevaluates the candidates and evidence saved by this run. Previous
        runs and saved lists keep their original criteria. Examples: “Exclude
        agencies” and “Relax must-have location India”. The new run keeps the
        same limits and counts toward your allowance.
      </p>
      <form onSubmit={(event) => void submit(event)}>
        <label htmlFor={`refine-${sourceJobId}`} className="sr-only">
          Refinement prompt
        </label>
        <textarea
          id={`refine-${sourceJobId}`}
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          maxLength={500}
          rows={2}
          placeholder="Exclude consultancies"
          disabled={busy}
        />
        <button
          type="submit"
          className="text-button"
          disabled={busy || prompt.trim().length < 3}
        >
          {busy ? "Starting refinement…" : "Refine and run"}
        </button>
      </form>
      {error && <p role="alert">{error}</p>}
    </details>
  );
}
