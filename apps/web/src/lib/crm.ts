import type { components } from "../generated/api";

export type CrmDestination = components["schemas"]["DestinationOutput"];
export type CrmDelivery = components["schemas"]["skriller__crm__router__DeliveryOutput"];
type CrmConsent = components["schemas"]["OAuthConsentOutput"];

const uuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
const validDestination = (value: unknown): value is CrmDestination => {
  if (!value || typeof value !== "object") return false;
  const row = value as CrmDestination;
  if (Object.keys(row).some((key) => !["id", "instance_url", "enabled", "expires_at", "generation"].includes(key))) return false;
  try { const url = new URL(row.instance_url); return uuid(row.id) && url.protocol === "https:" && /(^|\.)salesforce\.com$/i.test(url.hostname) && typeof row.enabled === "boolean" && Number.isInteger(row.generation) && Number.isFinite(Date.parse(row.expires_at)); } catch { return false; }
};
const validDelivery = (value: unknown): value is CrmDelivery => {
  if (!value || typeof value !== "object") return false;
  const row = value as CrmDelivery;
  return Object.keys(row).every((key) => ["id", "destination_id", "entity_id", "state", "attempts", "last_code"].includes(key)) && uuid(row.id) && uuid(row.destination_id) && uuid(row.entity_id) && ["pending", "delivering", "succeeded", "failed", "suppressed", "cancelled"].includes(row.state) && Number.isInteger(row.attempts) && row.attempts >= 0 && (row.last_code === null || typeof row.last_code === "string");
};
export function crmConsentState(consent: CrmConsent, origin: string) {
  const url = new URL(consent.authorization_url);
  if (!uuid(consent.consent_id) || !Number.isFinite(Date.parse(consent.expires_at)) || Date.parse(consent.expires_at) <= Date.now() || !["https://login.salesforce.com", "https://test.salesforce.com"].includes(url.origin) || url.pathname !== "/services/oauth2/authorize" || url.searchParams.get("response_type") !== "code" || url.searchParams.get("code_challenge_method") !== "S256" || url.searchParams.get("redirect_uri") !== `${origin}/connections/salesforce/callback` || !/^[A-Za-z0-9_-]{32,128}$/.test(url.searchParams.get("state") || "")) throw new Error("Salesforce consent response is invalid. Ask the operator to check OAuth settings.");
  return url.searchParams.get("state")!;
}

export function createCrmClient(request: (path: string, init?: RequestInit) => Promise<unknown>) {
  const base = (workspace: string) => `/v1/workspaces/${encodeURIComponent(workspace)}/crm`;
  const post = (body?: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });
  return {
    async crmStart(workspace: string) {
      const value = await request(base(workspace) + "/oauth/start", post({ opt_in: true })) as CrmConsent;
      crmConsentState(value, typeof window === "undefined" ? "https://invalid.local" : window.location.origin);
      return value;
    },
    async crmComplete(workspace: string, consent: string, state: string, code: string) {
      const value = await request(base(workspace) + "/oauth/complete", post({ consent_id: consent, state, code }));
      if (!validDestination(value)) throw new Error("Unexpected Salesforce connection response.");
      return value;
    },
    async crmDestinations(workspace: string) {
      const value = await request(base(workspace) + "/destinations");
      if (!Array.isArray(value) || value.length > 3 || !value.every(validDestination)) throw new Error("Unexpected Salesforce connection response.");
      return value as CrmDestination[];
    },
    async crmRevoke(workspace: string, id: string) {
      const value = await request(base(workspace) + `/destinations/${encodeURIComponent(id)}/revoke`, post());
      if (!validDestination(value) || value.id !== id) throw new Error("Unexpected Salesforce connection response.");
      return value;
    },
    async crmRefresh(workspace: string, id: string) {
      const value = await request(base(workspace) + `/destinations/${encodeURIComponent(id)}/refresh`, post());
      if (!validDestination(value) || value.id !== id) throw new Error("Unexpected Salesforce connection response.");
      return value;
    },
    async crmDeliver(workspace: string, input: { destination_id: string; plan_id: string; entity_id: string; field_map: Record<string, string>; selected_near: boolean; opt_in: true; idempotency_key: string }) {
      const value = await request(base(workspace) + "/deliveries", post(input)) as CrmDelivery;
      if (!validDelivery(value) || value.entity_id !== input.entity_id || value.destination_id !== input.destination_id) throw new Error("Unexpected Salesforce delivery response.");
      return value;
    },
    async crmDeliveries(workspace: string) {
      const value = await request(base(workspace) + "/deliveries");
      if (!Array.isArray(value) || value.length > 100 || !value.every(validDelivery)) throw new Error("Unexpected Salesforce delivery response.");
      return value as CrmDelivery[];
    },
    async crmCancelDelivery(workspace: string, id: string) {
      const value = await request(base(workspace) + `/deliveries/${encodeURIComponent(id)}/cancel`, post()) as CrmDelivery;
      if (!validDelivery(value) || value.id !== id) throw new Error("Unexpected Salesforce delivery response.");
      return value;
    },
  };
}
