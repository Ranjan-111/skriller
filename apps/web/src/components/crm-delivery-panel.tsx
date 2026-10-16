"use client";

import { useEffect, useRef, useState } from "react";
import type { createApi, ResearchCandidate } from "../lib/api";
import type { CrmDelivery, CrmDestination } from "../lib/crm";

const fields = [
  ["last_name", "Last name"], ["company_name", "Company"], ["role", "Title"],
  ["company_location", "City"], ["country", "Country"], ["company_website", "Website"],
] as const;
const targets = ["FirstName", "LastName", "Company", "Title", "Website", "City", "Country"] as const;

export function CrmDeliveryPanel({ api, workspaceId, planId, candidates, confirmed, near }: { api: ReturnType<typeof createApi>; workspaceId: string; planId: string; candidates: ResearchCandidate[]; confirmed: string[]; near: string[] }) {
  const [owner, setOwner] = useState(false);
  const [destinations, setDestinations] = useState<CrmDestination[]>([]);
  const [deliveries, setDeliveries] = useState<CrmDelivery[]>([]);
  const [entity, setEntity] = useState("");
  const [destination, setDestination] = useState("");
  const [fieldMap, setFieldMap] = useState<Record<string, string>>({ last_name: "LastName", company_name: "Company" });
  const [nearConfirmed, setNearConfirmed] = useState(false);
  const [optIn, setOptIn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const idempotency = useRef<{ signature: string; key: string } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setOwner(false); setDestinations([]); setDeliveries([]); setEntity(""); setOptIn(false); setNearConfirmed(false); idempotency.current = null; setError("");
    void api.allowance().then(async (access) => {
      if (controller.signal.aborted || !access.can_manage) return;
      setOwner(true);
      const [connections, sends] = await Promise.all([api.crmDestinations(workspaceId), api.crmDeliveries(workspaceId)]);
      if (!controller.signal.aborted) { setDestinations(connections); setDestination((value) => connections.some((item) => item.id === value && item.enabled) ? value : connections.find((item) => item.enabled)?.id ?? ""); setDeliveries(sends); }
    }).catch((reason) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "CRM delivery setup could not be loaded."); });
    return () => controller.abort();
  }, [api, workspaceId, revision]);
  const eligible = candidates.filter((candidate) => confirmed.includes(candidate.id) || near.includes(candidate.id));
  const map = Object.fromEntries(Object.entries(fieldMap).filter(([, value]) => value));
  const mappingValid = map.last_name === "LastName" && map.company_name === "Company" && new Set(Object.values(map)).size === Object.values(map).length;
  async function submit() {
    if (!entity || !destination || !mappingValid || !optIn) return;
    setBusy(true); setError("");
    try {
      const isNear = near.includes(entity);
      if (isNear && !nearConfirmed) throw new Error("Confirm that this near match should remain marked as a near match in Salesforce.");
      const signature = JSON.stringify([workspaceId, destination, planId, entity, map, isNear]);
      if (!idempotency.current || idempotency.current.signature !== signature) idempotency.current = { signature, key: globalThis.crypto.randomUUID() };
      await api.crmDeliver(workspaceId, { destination_id: destination, plan_id: planId, entity_id: entity, field_map: map, selected_near: isNear, opt_in: true, idempotency_key: idempotency.current.key });
      idempotency.current = null;
      setOptIn(false); setNearConfirmed(false); setRevision((value) => value + 1);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "CRM delivery could not be queued."); }
    finally { setBusy(false); }
  }
  async function cancel(id: string) { setBusy(true); setError(""); try { await api.crmCancelDelivery(workspaceId, id); setRevision((value) => value + 1); } catch (reason) { setError(reason instanceof Error ? reason.message : "CRM delivery could not be cancelled."); } finally { setBusy(false); } }
  return <details className="workspace-allowance analytics-panel">
    <summary>Send a qualified record to Salesforce</summary>
    <p>Only currently confirmed or near-match records are selectable. The service rechecks evidence, suppression and deletion before sending.</p>
    {error && <p role="alert">{error}</p>}
    {!owner ? <p>CRM delivery is available to the workspace owner after a Salesforce destination is connected.</p> : <>
      {!destinations.some((item) => item.enabled) ? <p>No active Salesforce destination is available. Connect one in the Salesforce panel below.</p> : <>
        <label>Qualified record<select value={entity} disabled={busy} onChange={(event) => { setEntity(event.target.value); setOptIn(false); setNearConfirmed(false); }}><option value="">Choose a current result</option>{eligible.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.title || candidate.url} · {near.includes(candidate.id) ? "near match" : "confirmed"}</option>)}</select></label>
        <label>Salesforce destination<select value={destination} disabled={busy} onChange={(event) => setDestination(event.target.value)}>{destinations.filter((item) => item.enabled).map((item) => <option key={item.id} value={item.id}>{new URL(item.instance_url).hostname}</option>)}</select></label>
        <fieldset><legend>Map research fields to Salesforce Lead fields</legend>{fields.map(([source, label]) => <label key={source}>{label}<select value={fieldMap[source] ?? ""} disabled={busy || source === "last_name" || source === "company_name"} onChange={(event) => setFieldMap((value) => ({ ...value, [source]: event.target.value }))}><option value="">Do not send</option>{targets.map((target) => <option key={target} value={target}>{target}</option>)}</select></label>)}<p>Last name and company are required. Email and phone fields are excluded from this pilot.</p></fieldset>
        {entity && near.includes(entity) && <label><input type="checkbox" checked={nearConfirmed} disabled={busy} onChange={(event) => setNearConfirmed(event.target.checked)} /> I reviewed this near match; keep its near-match status in Salesforce.</label>}
        <label><input type="checkbox" checked={optIn} disabled={busy || !entity || !mappingValid || (near.includes(entity) && !nearConfirmed)} onChange={(event) => setOptIn(event.target.checked)} /> I authorize sending this selected record and mapped fields to Salesforce.</label>
        <button type="button" className="text-button" disabled={busy || !entity || !destination || !mappingValid || !optIn} onClick={() => void submit()}>{busy ? "Sending…" : "Queue Salesforce delivery"}</button>
      </>}
      <div aria-live="polite"><h4>Recent CRM deliveries</h4>{deliveries.length ? <ul>{deliveries.map((item) => <li key={item.id}>Record {item.entity_id.slice(0, 8)} · {item.state}{["pending", "delivering"].includes(item.state) && <button type="button" className="text-button" disabled={busy} onClick={() => void cancel(item.id)}>Cancel</button>}</li>)}</ul> : <p>No CRM deliveries for this workspace.</p>}</div>
    </>}
  </details>;
}
