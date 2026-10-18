"use client";

import { useEffect, useRef, useState } from "react";
import type { createApi } from "../lib/api";
import {
  captureRedditCallback,
  consumeRedditConsent,
  REDDIT_CONSENT_KEY,
  redditConsentState,
  type RedditCallback,
  type RedditConsentMetadata,
} from "../lib/reddit-oauth";

export function RedditConnectionPanel({
  api,
  userId,
  identityStatus,
  refreshKey,
  navigate = (url: string) => window.location.assign(url),
}: {
  api: ReturnType<typeof createApi>;
  userId?: string;
  identityStatus: string;
  refreshKey?: number;
  navigate?: (url: string) => void;
}) {
  const [context, setContext] = useState<{
    uid: string;
    workspace: string;
    owner: boolean;
  } | null>(null);
  const [consents, setConsents] = useState<RedditConsentMetadata[]>([]);
  const [metadataReady, setMetadataReady] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const callback = useRef<RedditCallback | null>(null);
  const captured = useRef(false);
  const epoch = useRef(0);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => {
    if (captured.current) return;
    captured.current = true;
    if (window.location.pathname !== "/connections/reddit/callback") return;
    const result = captureRedditCallback(window.location.href);
    if (!result) return;
    callback.current = result.callback;
    window.history.replaceState(window.history.state, "", result.cleanUrl);
  }, []);

  useEffect(() => {
    const generation = ++epoch.current;
    controller.current?.abort();
    setContext(null);
    setConsents([]);
    setMetadataReady(false);
    setError("");
    setBusy(false);
    if (identityStatus === "loading") return;
    if (!userId || identityStatus !== "signed_in") {
      try {
        sessionStorage.removeItem(REDDIT_CONSENT_KEY);
      } catch {
        /* storage may be unavailable */
      }
      return;
    }
    void api
      .allowance()
      .then((value) => {
        if (generation === epoch.current)
          setContext({
            uid: userId,
            workspace: value.workspace_id,
            owner: value.can_manage,
          });
      })
      .catch(() => {
        if (generation === epoch.current)
          setError("Reddit workspace could not be loaded. Try again.");
      });
    return () => {
      epoch.current++;
      controller.current?.abort();
    };
  }, [api, userId, identityStatus, retry]);

  useEffect(() => {
    if (!context || context.uid !== userId) return;
    if (!context.owner) {
      setMetadataReady(true);
      try {
        sessionStorage.removeItem(REDDIT_CONSENT_KEY);
      } catch {
        /* storage may be unavailable */
      }
      return;
    }
    const nextController = new AbortController();
    controller.current?.abort();
    controller.current = nextController;
    const generation = epoch.current;
    setBusy(true);
    void (async () => {
      if (callback.current) {
        const result = callback.current;
        callback.current = null;
        const intent = consumeRedditConsent(
          sessionStorage,
          result,
          context.uid,
          context.workspace,
        );
        const completed = await api.redditComplete(
          context.workspace,
          intent.consent,
          intent.state,
          result.code!,
          nextController.signal,
        );
        if (!completed.id)
          throw new Error(
            "Reddit connection could not be confirmed. Reconnect and try again.",
          );
      }
      return api.redditConsents(context.workspace, nextController.signal);
    })()
      .then((rows) => {
        if (generation === epoch.current && !nextController.signal.aborted) {
          setConsents(rows);
          setMetadataReady(true);
        }
      })
      .catch((reason) => {
        if (generation === epoch.current && !nextController.signal.aborted)
          setError(
            reason instanceof Error
              ? reason.message
              : "Reddit connections could not be loaded.",
          );
      })
      .finally(() => {
        if (generation === epoch.current && !nextController.signal.aborted)
          setBusy(false);
      });
    return () => nextController.abort();
  }, [api, context, userId, retry, refreshKey]);

  if (!userId || identityStatus !== "signed_in") return null;
  const current = context?.uid === userId ? context : null;
  const active = consents.filter((row) => row.state === "active");
  const run = async (operation: (signal: AbortSignal) => Promise<void>) => {
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    const generation = epoch.current;
    setBusy(true);
    setError("");
    try {
      await operation(next.signal);
      if (generation === epoch.current && !next.signal.aborted)
        setRetry((value) => value + 1);
    } catch (reason) {
      if (generation === epoch.current && !next.signal.aborted)
        setError(
          reason instanceof Error
            ? reason.message
            : "Reddit connection request failed. Try again.",
        );
    } finally {
      if (generation === epoch.current && !next.signal.aborted) setBusy(false);
    }
  };

  return (
    <details className="workspace-allowance analytics-panel">
      <summary>Reddit direct access</summary>
      <p>
        Connect the workspace owner’s Reddit account for permitted direct reads.
        A fresh run started by the owner can renew access near expiry, without
        extending the consent retention date. Members cannot renew the owner’s
        access, and an old checkpoint needs a fresh run. Indexed Reddit search
        stays available without a connection.
      </p>
      {error && <p role="alert">{error}</p>}
      {!current ? (
        <button
          className="text-button"
          type="button"
          disabled={!error}
          onClick={() => setRetry((value) => value + 1)}
        >
          {error ? "Retry Reddit workspace" : "Checking Reddit workspace…"}
        </button>
      ) : !current.owner ? (
        <p>
          Only the workspace owner can connect Reddit. Indexed Reddit search
          remains available.
        </p>
      ) : (
        <>
          <div className="analytics-actions">
            <button
              className="text-button"
              type="button"
              disabled={busy || !metadataReady || consents.length >= 3}
              onClick={() =>
                void run(async (signal) => {
                  const consent = await api.redditStart(
                    current.workspace,
                    signal,
                  );
                  if (signal.aborted) return;
                  const state = redditConsentState(
                    consent,
                    window.location.origin,
                  );
                  sessionStorage.setItem(
                    REDDIT_CONSENT_KEY,
                    JSON.stringify({
                      uid: userId,
                      workspace: current.workspace,
                      consent: consent.consent_id,
                      state,
                      expires: Date.parse(consent.expires_at),
                    }),
                  );
                  navigate(consent.authorization_url);
                })
              }
            >
              Connect Reddit
            </button>
            <button
              className="text-button"
              type="button"
              disabled={busy}
              onClick={() => setRetry((value) => value + 1)}
            >
              Reload connections
            </button>
          </div>
          {!active.length ? (
            <p>
              {busy || !metadataReady
                ? "Loading Reddit connections…"
                : "No Reddit account is connected."}
            </p>
          ) : (
            active.map((connection) => (
              <div className="analytics-actions" key={connection.consent_id}>
                <p>
                  {connection.access_state === "active"
                    ? "Connected"
                    : connection.access_state === "expired"
                      ? "Access expired"
                      : "Disconnected"}{" "}
                  · access expires{" "}
                  {connection.access_expires_at
                    ? new Date(connection.access_expires_at).toLocaleString()
                    : "unknown"}{" "}
                  · consent retained until{" "}
                  {new Date(connection.expires_at).toLocaleDateString()}
                </p>
                <button
                  className="text-button"
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    void run(async (signal) => {
                      const replacement = await api.redditRefresh(
                        current.workspace,
                        connection.consent_id,
                        signal,
                      );
                      if (replacement.id === connection.connection_id)
                        throw new Error(
                          "Reddit refresh did not replace the connection. Try again.",
                        );
                    })
                  }
                >
                  Refresh access
                </button>
                <button
                  className="text-button"
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    void run(async (signal) => {
                      await api.redditRevoke(
                        current.workspace,
                        connection.consent_id,
                        signal,
                      );
                    })
                  }
                >
                  Disconnect locally
                </button>
              </div>
            ))
          )}
          {active.length > 0 && (
            <p>
              Disconnect removes local access; it does not revoke the grant at
              Reddit. Refresh creates a new connection, so older research
              checkpoints need a new run to use it.
            </p>
          )}
          <p>
            Direct Reddit access is optional. Live account access has not been
            accepted for this deployment.
          </p>
        </>
      )}
    </details>
  );
}
