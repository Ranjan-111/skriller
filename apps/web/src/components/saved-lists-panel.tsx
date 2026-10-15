"use client";

import { useEffect, useState } from "react";
import {
  safeSourceUrl,
  type createApi,
  type ResearchCandidate,
  type SavedList,
  type SavedListSnapshot,
} from "../lib/api";

export function SavedListsPanel({
  api,
  workspaceId,
  planId,
  candidates,
}: {
  api: ReturnType<typeof createApi>;
  workspaceId: string;
  planId: string | null;
  candidates: ResearchCandidate[];
}) {
  const [lists, setLists] = useState<SavedList[] | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [activeList, setActiveList] = useState("");
  const [snapshot, setSnapshot] = useState<SavedListSnapshot | null>(null);
  const [historyRevision, setHistoryRevision] = useState("");
  const [latestRevision, setLatestRevision] = useState(0);
  const [name, setName] = useState("Research results");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setLists(null);
    setActiveList("");
    setSnapshot(null);
    setSelected([]);
    setLatestRevision(0);
    setError("");
    setNotice("");
    void api
      .savedLists(workspaceId, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setLists(value);
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted)
          setError(
            failure instanceof Error
              ? failure.message
              : "Saved lists could not be loaded.",
          );
      });
    return () => controller.abort();
  }, [api, workspaceId]);

  useEffect(() => {
    if (!activeList) {
      setSnapshot(null);
      return;
    }
    const controller = new AbortController();
    setSnapshot(null);
    setError("");
    setHistoryRevision("");
    void api
      .savedListSnapshot(workspaceId, activeList, undefined, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) {
          setSnapshot(value);
          setLatestRevision(value.revision);
        }
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted)
          setError(
            failure instanceof Error
              ? failure.message
              : "Saved snapshot could not be loaded.",
          );
      });
    return () => controller.abort();
  }, [api, workspaceId, activeList]);

  const currentIds = selected.slice(0, 100);
  async function save() {
    if (!planId || currentIds.length === 0) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const list = await api.createSavedList(
        workspaceId,
        name,
        planId,
        currentIds,
      );
      setLists((value) => [
        list,
        ...(value ?? []).filter((item) => item.id !== list.id),
      ]);
      setActiveList(list.id);
      const first = await api.savedListSnapshot(workspaceId, list.id);
      setSnapshot(first);
      setLatestRevision(first.revision);
      setNotice(
        "Saved as immutable revision 1. It contains persisted reviewed facts only; no sources were fetched.",
      );
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "The list could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function refresh() {
    if (!snapshot || !activeList) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const next = await api.refreshSavedList(
        workspaceId,
        activeList,
        snapshot.payload.members.map((member) => member.entity_id),
        snapshot.revision,
      );
      setSnapshot(next);
      setHistoryRevision("");
      setLatestRevision(next.revision);
      setNotice(
        `Created revision ${next.revision}. Previous revisions remain unchanged; refresh uses persisted reviewed facts only.`,
      );
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "The list could not be refreshed.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function showRevision(revision: string) {
    setHistoryRevision(revision);
    setError("");
    try {
      setSnapshot(
        await api.savedListSnapshot(workspaceId, activeList, Number(revision)),
      );
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "That revision is unavailable.",
      );
    }
  }

  return (
    <section
      className="candidate-provenance saved-lists"
      aria-labelledby="saved-lists-title"
    >
      <h3 id="saved-lists-title">Saved lists</h3>
      <p className="candidate-meta">
        Save result IDs to a workspace list. Revisions freeze reviewed facts and
        evidence; refresh rechecks persisted data and does not revisit websites.
      </p>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {lists === null ? (
        <p role="status">Loading saved lists…</p>
      ) : lists.length === 0 ? (
        <p>No saved lists in this workspace.</p>
      ) : (
        <label>
          Open list{" "}
          <select
            aria-label="Open saved list"
            value={activeList}
            onChange={(event) => setActiveList(event.target.value)}
          >
            <option value="">Choose a saved list</option>
            {lists.map((list) => (
              <option key={list.id} value={list.id}>
                {list.name}
              </option>
            ))}
          </select>
        </label>
      )}
      {activeList && snapshot && (
        <div className="saved-list-snapshot">
          <p>
            <strong>Revision {snapshot.revision}</strong> ·{" "}
            {new Date(snapshot.payload.snapshot_at).toLocaleString()} ·{" "}
            {snapshot.payload.members.length} members ·{" "}
            {snapshot.payload.omitted.length} suppressed
          </p>
          <label>
            Inspect revision{" "}
            <select
              aria-label="Inspect saved list revision"
              value={historyRevision || String(latestRevision)}
              onChange={(event) =>
                event.target.value === String(latestRevision)
                  ? (setHistoryRevision(""),
                    void api
                      .savedListSnapshot(workspaceId, activeList)
                      .then((value) => setSnapshot(value))
                      .catch((failure: unknown) =>
                        setError(
                          failure instanceof Error
                            ? failure.message
                            : "Latest snapshot is unavailable.",
                        ),
                      ))
                  : void showRevision(event.target.value)
              }
            >
              {Array.from(
                { length: latestRevision },
                (_, index) => latestRevision - index,
              ).map((revision) => (
                <option key={revision} value={revision}>
                  Revision {revision}
                  {revision === latestRevision ? " (latest)" : " (frozen)"}
                </option>
              ))}
            </select>
          </label>
          <ul>
            {snapshot.payload.members.map((member) => (
              <li key={member.entity_id}>
                {member.display_name ?? "Unnamed record"} ·{" "}
                {member.fit.status.replaceAll("_", " ")} ·{" "}
                {member.values.length} reviewed facts
                {member.values.length > 0 && (
                  <ul>
                    {member.values.map((value) => (
                      <li
                        key={`${value.field}-${value.claim_ids?.join("-") ?? value.value}`}
                      >
                        {value.field.replaceAll("_", " ")}:{" "}
                        {String(value.value)}
                        {value.evidence.map((evidence) => {
                          const href = safeSourceUrl(evidence.source_url);
                          return (
                            <span key={evidence.id}>
                              {" "}
                              ·{" "}
                              {href ? (
                                <a
                                  href={href}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                >
                                  {evidence.source_platform} evidence
                                </a>
                              ) : (
                                evidence.source_platform
                              )}{" "}
                              (
                              {new Date(
                                evidence.collected_at,
                              ).toLocaleDateString()}
                              )
                            </span>
                          );
                        })}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
          {snapshot.payload.omitted.length > 0 && (
            <p>Suppressed records are omitted from this revision.</p>
          )}
          {snapshot.revision !== latestRevision && (
            <p role="status">
              Historical snapshot. This view does not change the current list.
            </p>
          )}
          <button
            type="button"
            className="text-button"
            disabled={busy || historyRevision !== ""}
            onClick={() => void refresh()}
          >
            {busy ? "Refreshing…" : "Create a new persisted-facts revision"}
          </button>
        </div>
      )}
      {planId && candidates.length > 0 && (
        <details>
          <summary>
            Save current results ({Math.min(candidates.length, 100)} max)
          </summary>
          <label>
            List name{" "}
            <input
              aria-label="Saved list name"
              maxLength={120}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <div className="saved-list-candidates">
            {candidates.slice(0, 100).map((candidate) => (
              <label key={candidate.id}>
                <input
                  type="checkbox"
                  checked={selected.includes(candidate.id)}
                  onChange={(event) =>
                    setSelected((current) =>
                      event.target.checked
                        ? current.length < 100
                          ? [...current, candidate.id]
                          : current
                        : current.filter((id) => id !== candidate.id),
                    )
                  }
                />
                <span>{candidate.title}</span>
              </label>
            ))}
          </div>
          <button
            type="button"
            className="text-button"
            disabled={busy || selected.length === 0 || !name.trim()}
            onClick={() => void save()}
          >
            {busy
              ? "Saving snapshot…"
              : `Save ${selected.length} selected result${selected.length === 1 ? "" : "s"}`}
          </button>
        </details>
      )}
    </section>
  );
}
