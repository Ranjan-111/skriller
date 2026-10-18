"use client";

import { useEffect, useRef, useState } from "react";
import type { createApi } from "../lib/api";
import {
  captureXCallback,
  consumeXConsent,
  X_CONSENT_KEY,
  type XCallback,
  type XConsentMetadata,
} from "../lib/x-oauth";

type Intent = {
  uid: string;
  workspace: string;
  consent: string;
  state: string;
  expires: number;
};

export function XConnectionPanel({
  api,
  userId,
  identityStatus,
  onConnectedChange,
  navigate = (url: string) => window.location.assign(url),
}: {
  api: ReturnType<typeof createApi>;
  userId?: string;
  identityStatus: string;
  onConnectedChange?: (connected: boolean) => void;
  navigate?: (url: string) => void;
}) {
  const [context, setContext] = useState<{
    uid: string;
    workspace: string;
    owner: boolean;
  } | null>(null);
  const [consents, setConsents] = useState<XConsentMetadata[]>([]);
  const [metadataReady, setMetadataReady] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const callback = useRef<XCallback | null>(null);
  const captured = useRef(false);
  const epoch = useRef(0);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => {
    if (captured.current) return;
    captured.current = true;
    if (window.location.pathname !== "/connections/x/callback") return;
    const capturedCallback = captureXCallback(window.location.href);
    if (!capturedCallback) return;
    callback.current = capturedCallback.callback;
    window.history.replaceState(
      window.history.state,
      "",
      capturedCallback.cleanUrl,
    );
  }, []);

  useEffect(() => {
    const generation = ++epoch.current;
    controller.current?.abort();
    setContext(null);
    setConsents([]);
    setMetadataReady(false);
    setError("");
    setBusy(false);
    onConnectedChange?.(false);
    if (identityStatus === "loading") return;
    if (!userId || identityStatus !== "signed_in") {
      try {
        sessionStorage.removeItem(X_CONSENT_KEY);
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
          setError("X workspace could not be loaded. Try again.");
      });
    return () => {
      epoch.current++;
      controller.current?.abort();
    };
  }, [api, userId, identityStatus, retry, onConnectedChange]);

  useEffect(() => {
    if (!context || context.uid !== userId) return;
    if (!context.owner) {
      setMetadataReady(true);
      try {
        sessionStorage.removeItem(X_CONSENT_KEY);
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
        const intent = consumeXConsent(
          sessionStorage,
          result,
          context.uid,
          context.workspace,
        );
        const completed = await api.xComplete(
          context.workspace,
          intent.consent,
          intent.state,
          result.code!,
          nextController.signal,
        );
        if (!completed.id)
          throw new Error(
            "X connection could not be confirmed. Reconnect and try again.",
          );
      }
      return api.xConsents(context.workspace, nextController.signal);
    })()
      .then((rows) => {
        if (generation === epoch.current && !nextController.signal.aborted) {
          setConsents(rows);
          setMetadataReady(true);
          onConnectedChange?.(
            rows.some(
              (row) =>
                row.state === "active" &&
                row.access_state === "active" &&
                !!row.connection_id,
            ),
          );
        }
      })
      .catch((reason) => {
        if (generation === epoch.current && !nextController.signal.aborted)
          setError(
            reason instanceof Error
              ? reason.message
              : "X connections could not be loaded.",
          );
      })
      .finally(() => {
        if (generation === epoch.current && !nextController.signal.aborted)
          setBusy(false);
      });
    return () => nextController.abort();
  }, [api, context, userId, retry, onConnectedChange]);

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
            : "X connection request failed. Try again.",
        );
    } finally {
      if (generation === epoch.current && !next.signal.aborted) setBusy(false);
    }
  };
  return (
    <details className="workspace-allowance analytics-panel">
      <summary>X connection</summary>
      <p>
        Connect the workspace owner’s X account to read permitted public posts.
        X direct reads are optional and require an active connection.
      </p>
      {error && <p role="alert">{error}</p>}
      {!current ? (
        <button
          className="text-button"
          type="button"
          disabled={!error}
          onClick={() => setRetry((value) => value + 1)}
        >
          {error ? "Retry X workspace" : "Checking X workspace…"}
        </button>
      ) : !current.owner ? (
        <p>
          Only the workspace owner can connect X. Existing indexed results may
          still be available.
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
                  const consent = await api.xStart(current.workspace, signal);
                  if (signal.aborted) return;
                  const state = new URL(
                    consent.authorization_url,
                  ).searchParams.get("state")!;
                  const intent: Intent = {
                    uid: userId,
                    workspace: current.workspace,
                    consent: consent.consent_id,
                    state,
                    expires: Date.parse(consent.expires_at),
                  };
                  sessionStorage.setItem(X_CONSENT_KEY, JSON.stringify(intent));
                  navigate(consent.authorization_url);
                })
              }
            >
              Connect X
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
                ? "Loading X connections…"
                : "No X account is connected."}
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
                      const replacement = await api.xRefresh(
                        current.workspace,
                        connection.consent_id,
                        signal,
                      );
                      if (replacement.id === connection.connection_id)
                        throw new Error(
                          "X refresh did not replace the connection. Try again.",
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
                      await api.xRevoke(
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
              X. Refresh creates a new connection, so older research checkpoints
              need a new run to use it.
            </p>
          )}
          <p>
            Direct X access is optional and does not claim that a live account
            read has been tested.
          </p>
        </>
      )}
    </details>
  );
}
