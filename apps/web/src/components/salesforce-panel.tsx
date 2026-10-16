"use client";

import { useEffect, useRef, useState } from "react";
import type { createApi } from "../lib/api";
import { crmConsentState, type CrmDestination } from "../lib/crm";

const KEY = "skriller.salesforce.consent.v1";
type Callback = { code: string | null; state: string | null; invalid: boolean; denied: boolean };
type Intent = { uid: string; workspace: string; consent: string; state: string; expires: number };

export function SalesforcePanel({ api, userId, identityStatus, navigate = (url: string) => window.location.assign(url) }: { api: ReturnType<typeof createApi>; userId?: string; identityStatus: string; navigate?: (url: string) => void }) {
  const [context, setContext] = useState<{ uid: string; workspace: string; owner: boolean } | null>(null);
  const [destinations, setDestinations] = useState<CrmDestination[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const callback = useRef<Callback | null>(null);
  const captured = useRef(false);
  const epoch = useRef(0);

  useEffect(() => {
    if (captured.current) return;
    captured.current = true;
    if (window.location.pathname !== "/connections/salesforce/callback") return;
    const url = new URL(window.location.href);
    const code = url.searchParams.get("code"), state = url.searchParams.get("state");
    callback.current = { code, state, denied: url.searchParams.has("error"), invalid: url.searchParams.getAll("code").length !== 1 || url.searchParams.getAll("state").length !== 1 || !code || code.length > 8192 || !state || !/^[A-Za-z0-9_-]{32,128}$/.test(state) };
    for (const key of ["code", "state", "error", "error_description", "scope"]) url.searchParams.delete(key);
    window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
  }, []);

  useEffect(() => {
    const generation = ++epoch.current;
    setContext(null); setDestinations([]); setError(""); setBusy(false);
    if (!userId || identityStatus !== "signed_in") return;
    void api.allowance().then((value) => { if (generation === epoch.current) setContext({ uid: userId, workspace: value.workspace_id, owner: value.can_manage }); }).catch(() => { if (generation === epoch.current) setError("Salesforce workspace could not be loaded. Try again."); });
    return () => { epoch.current++; };
  }, [api, userId, identityStatus, retry]);

  useEffect(() => {
    if (!context || context.uid !== userId || !context.owner) return;
    let active = true;
    const generation = epoch.current;
    setBusy(true);
    void (async () => {
      if (callback.current) {
        const result = callback.current; callback.current = null;
        const raw = sessionStorage.getItem(KEY); sessionStorage.removeItem(KEY);
        let intent: Intent | null = null;
        try { intent = JSON.parse(raw || "null") as Intent; } catch { /* rejected below */ }
        if (!intent || result.denied || result.invalid || !result.code || intent.uid !== context.uid || intent.workspace !== context.workspace || intent.state !== result.state || !Number.isFinite(intent.expires) || intent.expires <= Date.now()) throw new Error("Salesforce consent expired, was declined, or belongs to another account or workspace. Connect again.");
        const destination = await api.crmComplete(context.workspace, intent.consent, intent.state, result.code);
        if (!destination.enabled) throw new Error("Salesforce connected but the destination is disabled.");
      }
      const rows = await api.crmDestinations(context.workspace);
      if (active && generation === epoch.current) setDestinations(rows);
    })().catch((reason) => { if (active && generation === epoch.current) setError(reason instanceof Error ? reason.message : "Salesforce connections could not be loaded."); }).finally(() => { if (active && generation === epoch.current) setBusy(false); });
    return () => { active = false; };
  }, [api, context, userId, retry]);

  if (!userId || identityStatus !== "signed_in") return null;
  const current = context?.uid === userId ? context : null;
  const run = async (operation: () => Promise<void>) => { setBusy(true); setError(""); try { await operation(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Salesforce request failed. Try again."); } finally { setBusy(false); } };
  return <details className="workspace-allowance analytics-panel">
    <summary>Salesforce CRM</summary>
    <p>Connect your workspace’s Salesforce destination. Delivery requires an explicit selection and consent for each qualified record.</p>
    {error && <p role="alert">{error}</p>}
    {!current ? <button className="text-button" type="button" disabled={!error} onClick={() => setRetry((value) => value + 1)}>{error ? "Retry Salesforce workspace" : "Checking Salesforce workspace…"}</button> : !current.owner ? <p>Only the workspace owner can connect a CRM destination.</p> : <>
      <div className="analytics-actions">
        <button className="text-button" type="button" disabled={busy} onClick={() => void run(async () => {
          const consent = await api.crmStart(current.workspace);
          const state = crmConsentState(consent, window.location.origin);
          sessionStorage.setItem(KEY, JSON.stringify({ uid: userId, workspace: current.workspace, consent: consent.consent_id, state, expires: Date.parse(consent.expires_at) }));
          navigate(consent.authorization_url);
        })}>Connect Salesforce</button>
        <button className="text-button" type="button" disabled={busy} onClick={() => setRetry((value) => value + 1)}>Reload connections</button>
      </div>
      {!destinations.length ? <p>{busy ? "Loading Salesforce connections…" : "No Salesforce destination is connected."}</p> : destinations.map((destination) => <div className="analytics-actions" key={destination.id}>
        <p>{new URL(destination.instance_url).hostname} · {destination.enabled ? "Connected" : "Disconnected"} · access expires {new Date(destination.expires_at).toLocaleDateString()}</p>
        <button className="text-button" type="button" disabled={busy || !destination.enabled} onClick={() => void run(async () => { await api.crmRefresh(current.workspace, destination.id); setRetry((value) => value + 1); })}>Refresh access</button>
        <button className="text-button" type="button" disabled={busy || !destination.enabled} onClick={() => void run(async () => { await api.crmRevoke(current.workspace, destination.id); setRetry((value) => value + 1); })}>Disconnect Salesforce</button>
      </div>)}
      <p>Research records are not sent from this panel. Choose a qualified record in its result view and review the field mapping and consent before delivery.</p>
    </>}
  </details>;
}
