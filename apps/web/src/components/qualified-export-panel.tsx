"use client";

import { useEffect, useRef, useState } from "react";
import type { createApi, ResearchCandidate } from "../lib/api";
import { saveQualifiedExport } from "../lib/qualified-exports";

export function QualifiedExportPanel({
  api,
  workspaceId,
  planId,
  candidates,
}: {
  api: ReturnType<typeof createApi>;
  workspaceId: string;
  planId: string;
  candidates: ResearchCandidate[];
}) {
  const confirmed = candidates
    .filter((candidate) => candidate.fit?.status === "confirmed")
    .map((candidate) => candidate.id);
  const signature = JSON.stringify([workspaceId, planId, confirmed]);
  const active = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    setBusy(false);
    setMessage("");
    return () => {
      active.current?.abort();
      active.current = null;
    };
  }, [signature]);
  async function download(format: "csv" | "json") {
    if (active.current || !confirmed.length || confirmed.length > 100) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setMessage("");
    try {
      const metadata = await api.qualifiedExport(
        workspaceId,
        planId,
        confirmed,
        format,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      const file = await api.qualifiedExportDownload(
        workspaceId,
        metadata.id,
        format,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      saveQualifiedExport(file, format);
      setMessage(`Downloaded ${metadata.row_count} confirmed records.`);
    } catch (error) {
      if (!controller.signal.aborted)
        setMessage(
          error instanceof Error
            ? error.message
            : "Export failed. Refresh results and try again.",
        );
    } finally {
      if (active.current === controller) {
        active.current = null;
        setBusy(false);
      }
    }
  }
  return (
    <section
      className="candidate-provenance"
      aria-label="Confirmed record export"
    >
      <h3>Download confirmed records</h3>
      <p>
        Export accepted fields and evidence for {confirmed.length} confirmed
        records. The server rechecks qualification and source freshness. Near
        matches and unverified sources are excluded.
      </p>
      {confirmed.length > 100 && (
        <p>
          Downloads support up to 100 confirmed records. Narrow this run before
          exporting.
        </p>
      )}
      <div className="source-exports">
        <button
          type="button"
          disabled={busy || !confirmed.length || confirmed.length > 100}
          onClick={() => void download("csv")}
        >
          {busy ? "Preparing download…" : "Download confirmed CSV"}
        </button>
        <button
          type="button"
          disabled={busy || !confirmed.length || confirmed.length > 100}
          onClick={() => void download("json")}
        >
          Download confirmed JSON
        </button>
      </div>
      <p role="status" aria-live="polite">
        {message}
      </p>
    </section>
  );
}
