"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, type WorkspaceAllowance, type createApi } from "../lib/api";

export function WorkspaceAllowancePanel({
  api,
  refreshKey,
}: {
  api: ReturnType<typeof createApi>;
  refreshKey?: string;
}) {
  const [allowance, setAllowance] = useState<WorkspaceAllowance | null>(null);
  const [enabled, setEnabled] = useState(true);
  const [results, setResults] = useState("25");
  const [sources, setSources] = useState("3");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [reload, setReload] = useState(0);
  const [saved, setSaved] = useState(false);
  const mounted = useRef(true);
  useEffect(() => {
    let active = true;
    mounted.current = true;
    void api
      .allowance()
      .then((data) => {
        if (!active) return;
        setAllowance(data);
        setEnabled(data.enabled);
        setResults(String(data.result_limit));
        setSources(String(data.source_limit));
        setError("");
      })
      .catch(() => {
        if (active)
          setError(
            "Workspace allowance could not be loaded. Reload to check it.",
          );
      });
    return () => {
      active = false;
      mounted.current = false;
    };
  }, [api, reload, refreshKey]);
  if (!allowance)
    return (
      <p className="candidate-meta">
        {error || "Checking workspace allowance…"}
        {error && (
          <button
            className="text-button"
            onClick={() => setReload((value) => value + 1)}
          >
            Reload allowance
          </button>
        )}
      </p>
    );
  const valid =
    Number.isInteger(Number(results)) &&
    Number(results) >= 1 &&
    Number(results) <= allowance.result_cap &&
    Number.isInteger(Number(sources)) &&
    Number(sources) >= 1 &&
    Number(sources) <= allowance.source_cap;
  return (
    <details className="workspace-allowance">
      <summary>
        Workspace allowance · {allowance.remaining_runs} runs remaining
      </summary>
      <p>
        {allowance.used_runs} of {allowance.run_limit} run admissions used.{" "}
        {allowance.tier === "trial"
          ? "Trial allowance"
          : "Manual pilot allowance"}
        .
      </p>
      <button
        className="text-button"
        onClick={() => setReload((value) => value + 1)}
      >
        Refresh allowance
      </button>
      {allowance.can_manage ? (
        <form
          aria-label="Workspace execution settings"
          onSubmit={async (event) => {
            event.preventDefault();
            if (!valid || saving) return;
            setSaving(true);
            setSaved(false);
            setError("");
            try {
              const next = await api.updateAllowance(allowance.workspace_id, {
                enabled,
                result_limit: Number(results),
                source_limit: Number(sources),
              });
              if (mounted.current) {
                setAllowance(next);
                setSaved(true);
              }
            } catch (e) {
              if (mounted.current)
                setError(
                  e instanceof ApiError
                    ? e.message
                    : "Settings could not be saved. Try again.",
                );
            } finally {
              if (mounted.current) setSaving(false);
            }
          }}
        >
          <label className="allowance-toggle">
            <input
              type="checkbox"
              checked={enabled}
              disabled={saving}
              onChange={(event) => {
                setEnabled(event.target.checked);
                setSaved(false);
              }}
            />{" "}
            Allow research execution
          </label>
          <div className="allowance-fields">
            <label>
              Results per run
              <input
                type="number"
                min={1}
                max={allowance.result_cap}
                value={results}
                disabled={saving}
                onChange={(event) => {
                  setResults(event.target.value);
                  setSaved(false);
                }}
              />
            </label>
            <label>
              Sources per run
              <input
                type="number"
                min={1}
                max={allowance.source_cap}
                value={sources}
                disabled={saving}
                onChange={(event) => {
                  setSources(event.target.value);
                  setSaved(false);
                }}
              />
            </label>
          </div>
          <p className="candidate-meta">
            Changing limits can pause runs that exceed them. The total run
            allowance is provisioned separately; saving does not reset usage.
          </p>
          <button
            className="secondary-button"
            type="submit"
            disabled={saving || !valid}
          >
            {saving ? "Saving settings…" : "Save workspace settings"}
          </button>
          {saved && <p role="status">Workspace settings saved.</p>}
        </form>
      ) : (
        <p>Only the workspace owner can change execution settings.</p>
      )}
      {!allowance.enabled && (
        <p>Research execution is paused by the workspace owner.</p>
      )}
      {error && <p role="status">{error}</p>}
    </details>
  );
}
