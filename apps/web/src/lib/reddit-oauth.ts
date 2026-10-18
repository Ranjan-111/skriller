import type { components } from "../generated/api";

export type RedditConnection = components["schemas"]["ConnectionMetadata"];
export type RedditConsent = components["schemas"]["RedditConsentOutput"];
export type RedditConsentMetadata =
  components["schemas"]["RedditConsentMetadata"];
export const REDDIT_CONSENT_KEY = "skriller.reddit-oauth.consent.v1";
export type RedditConsentIntent = {
  uid: string;
  workspace: string;
  consent: string;
  state: string;
  expires: number;
};
export type RedditCallback = {
  code: string | null;
  state: string | null;
  denied: boolean;
  invalid: boolean;
};

const uuid = (value: unknown): value is string =>
  typeof value === "string" &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    value,
  );

export function redditConsentState(consent: RedditConsent, origin: string) {
  const url = new URL(consent.authorization_url);
  const expected = [
    "response_type",
    "client_id",
    "redirect_uri",
    "scope",
    "state",
    "duration",
  ];
  if (
    Object.keys(consent).some(
      (key) => !["consent_id", "authorization_url", "expires_at"].includes(key),
    ) ||
    !uuid(consent.consent_id) ||
    !Number.isFinite(Date.parse(consent.expires_at)) ||
    Date.parse(consent.expires_at) <= Date.now() ||
    url.origin !== "https://www.reddit.com" ||
    !!url.username ||
    !!url.password ||
    !!url.hash ||
    url.pathname !== "/api/v1/authorize" ||
    [...url.searchParams.keys()].some((key) => !expected.includes(key)) ||
    expected.some((key) => url.searchParams.getAll(key).length !== 1) ||
    url.searchParams.get("response_type") !== "code" ||
    url.searchParams.get("redirect_uri") !==
      `${origin}/connections/reddit/callback` ||
    url.searchParams.get("scope") !== "read" ||
    url.searchParams.get("duration") !== "permanent" ||
    !/^[\x21-\x7e]{1,512}$/.test(url.searchParams.get("client_id") || "") ||
    !/^[A-Za-z0-9_-]{43,128}$/.test(url.searchParams.get("state") || "")
  )
    throw new Error(
      "Reddit consent response is invalid. Ask the operator to check OAuth settings.",
    );
  return url.searchParams.get("state")!;
}

export function validRedditMetadata(
  value: unknown,
): value is RedditConsentMetadata {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as RedditConsentMetadata;
  return (
    Object.keys(row).every((key) =>
      [
        "consent_id",
        "connection_id",
        "state",
        "expires_at",
        "access_expires_at",
        "access_state",
        "remote_revocation",
      ].includes(key),
    ) &&
    uuid(row.consent_id) &&
    (row.connection_id === null || uuid(row.connection_id)) &&
    ["pending", "exchanging", "active"].includes(row.state) &&
    Number.isFinite(Date.parse(row.expires_at)) &&
    (row.access_expires_at == null ||
      (typeof row.access_expires_at === "string" &&
        Number.isFinite(Date.parse(row.access_expires_at)))) &&
    (row.access_state == null ||
      ["active", "expired", "revoked"].includes(row.access_state)) &&
    row.remote_revocation === "not_performed"
  );
}

function validRedditConnection(
  value: unknown,
  workspace: string,
): value is RedditConnection {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as RedditConnection;
  return (
    Object.keys(row).every((key) =>
      [
        "id",
        "workspace_id",
        "source",
        "auth_kind",
        "scopes",
        "state",
        "expires_at",
        "access_validation",
        "remote_revocation",
      ].includes(key),
    ) &&
    uuid(row.id) &&
    row.workspace_id === workspace &&
    row.source === "reddit" &&
    row.auth_kind === "oauth" &&
    Array.isArray(row.scopes) &&
    row.scopes.length === 2 &&
    row.scopes.includes("read") &&
    row.scopes.includes("discover") &&
    row.state === "active" &&
    Number.isFinite(Date.parse(row.expires_at)) &&
    Date.parse(row.expires_at) > Date.now() &&
    row.access_validation === "not_performed" &&
    row.remote_revocation === "not_performed"
  );
}

export function validRedditMetadataList(
  value: unknown,
): value is RedditConsentMetadata[] {
  return (
    Array.isArray(value) &&
    value.length <= 3 &&
    value.every(validRedditMetadata)
  );
}

export function captureRedditCallback(href: string) {
  const url = new URL(href);
  if (!["code", "state", "error"].some((key) => url.searchParams.has(key)))
    return null;
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const callback: RedditCallback = {
    code,
    state,
    denied: url.searchParams.has("error"),
    invalid:
      url.searchParams.getAll("code").length !== 1 ||
      url.searchParams.getAll("state").length !== 1 ||
      !code ||
      code.length > 8192 ||
      !state ||
      !/^[A-Za-z0-9_-]{43,128}$/.test(state),
  };
  for (const key of ["code", "state", "error", "error_description", "scope"])
    url.searchParams.delete(key);
  return { callback, cleanUrl: url.pathname + url.search + url.hash };
}

export function consumeRedditConsent(
  storage: Pick<Storage, "getItem" | "removeItem">,
  callback: RedditCallback,
  uid: string,
  workspace: string,
): RedditConsentIntent {
  try {
    const raw = storage.getItem(REDDIT_CONSENT_KEY);
    storage.removeItem(REDDIT_CONSENT_KEY);
    const intent = JSON.parse(raw || "null") as RedditConsentIntent;
    if (
      !intent ||
      callback.denied ||
      callback.invalid ||
      !callback.code ||
      intent.uid !== uid ||
      intent.workspace !== workspace ||
      intent.state !== callback.state ||
      !uuid(intent.consent) ||
      !Number.isFinite(intent.expires) ||
      intent.expires <= Date.now()
    )
      throw new Error();
    return intent;
  } catch {
    throw new Error(
      "Reddit consent expired, was declined, or belongs to another account or workspace. Connect again.",
    );
  }
}

export function createRedditClient(
  request: (path: string, init?: RequestInit) => Promise<unknown>,
) {
  const base = (workspace: string) =>
    `/v1/workspaces/${encodeURIComponent(workspace)}/reddit/oauth`;
  const post = (body?: unknown): RequestInit => ({
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  return {
    async redditConsents(workspace: string, signal?: AbortSignal) {
      const value = await request(base(workspace), { signal });
      if (!validRedditMetadataList(value))
        throw new Error("Unexpected Reddit connection response.");
      return value;
    },
    async redditStart(workspace: string, signal?: AbortSignal) {
      const value = (await request(base(workspace) + "/start", {
        ...post({ opt_in: true }),
        signal,
      })) as RedditConsent;
      redditConsentState(
        value,
        typeof window === "undefined"
          ? "https://invalid.local"
          : window.location.origin,
      );
      return value;
    },
    async redditComplete(
      workspace: string,
      consent: string,
      state: string,
      code: string,
      signal?: AbortSignal,
    ) {
      const value = await request(base(workspace) + "/complete", {
        ...post({ consent_id: consent, state, code }),
        signal,
      });
      if (!validRedditConnection(value, workspace))
        throw new Error("Unexpected Reddit connection response.");
      return value;
    },
    async redditRefresh(
      workspace: string,
      consent: string,
      signal?: AbortSignal,
    ) {
      const value = await request(
        base(workspace) + `/${encodeURIComponent(consent)}/refresh`,
        { ...post(), signal },
      );
      if (!validRedditConnection(value, workspace))
        throw new Error("Unexpected Reddit connection response.");
      return value;
    },
    async redditRevoke(
      workspace: string,
      consent: string,
      signal?: AbortSignal,
    ) {
      const value = await request(
        base(workspace) + `/${encodeURIComponent(consent)}/revoke`,
        { ...post(), signal },
      );
      if (value !== null)
        throw new Error("Unexpected Reddit disconnect response.");
    },
  };
}
