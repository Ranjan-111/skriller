import { describe, expect, it, vi } from "vitest";
import { createApi } from "../src/lib/api";
import {
  captureXCallback,
  consumeXConsent,
  createXClient,
  X_CONSENT_KEY,
  xConsentState,
  type XConsentMetadata,
} from "../src/lib/x-oauth";

const workspace = "22222222-2222-4222-8222-222222222222";
const consentId = "11111111-1111-4111-8111-111111111111";
const connectionId = "33333333-3333-4333-8333-333333333333";
const state = "s".repeat(43);
function authorizationUrl(overrides: Record<string, string> = {}) {
  const url = new URL("https://x.com/i/oauth2/authorize");
  Object.entries({
    response_type: "code",
    client_id: "public-client",
    redirect_uri: "http://localhost:3000/connections/x/callback",
    scope: "tweet.read users.read offline.access",
    state,
    code_challenge: "c".repeat(43),
    code_challenge_method: "S256",
    ...overrides,
  }).forEach(([key, value]) => url.searchParams.set(key, value));
  return url.href;
}
const connection = {
  id: connectionId,
  workspace_id: workspace,
  source: "x" as const,
  auth_kind: "oauth" as const,
  scopes: ["read", "discover"],
  state: "active" as const,
  expires_at: "2099-01-01T00:00:00Z",
  access_validation: "not_performed" as const,
  remote_revocation: "not_performed" as const,
};
const metadata: XConsentMetadata = {
  consent_id: consentId,
  connection_id: connectionId,
  state: "active",
  expires_at: "2099-01-01T00:00:00Z",
  access_expires_at: "2099-01-01T00:00:00Z",
  access_state: "active",
  remote_revocation: "not_performed",
};

describe("X OAuth client contracts", () => {
  it("accepts only the fixed X endpoint, PKCE, callback, and required read scopes", () => {
    expect(
      xConsentState(
        {
          consent_id: consentId,
          authorization_url: authorizationUrl(),
          expires_at: "2099-01-01T00:00:00Z",
        },
        "http://localhost:3000",
      ),
    ).toBe(state);
    for (const url of [
      authorizationUrl({ scope: "tweet.read users.read" }),
      authorizationUrl({ code_challenge_method: "plain" }),
      authorizationUrl({ redirect_uri: "https://evil.example/callback" }),
      authorizationUrl({
        scope: "tweet.read users.read offline.access users.write",
      }),
      `${authorizationUrl()}&state=${state}`,
      `${authorizationUrl()}#unexpected`,
      authorizationUrl().replace(
        "https://x.com",
        "https://user:password@x.com",
      ),
      authorizationUrl().replace("https://x.com", "https://evil.example"),
    ]) {
      expect(() =>
        xConsentState(
          {
            consent_id: consentId,
            authorization_url: url,
            expires_at: "2099-01-01T00:00:00Z",
          },
          "http://localhost:3000",
        ),
      ).toThrow(/X consent response is invalid/);
    }
  });
  it("cleans OAuth values from callback URL before auth and consumes account-bound intent once", () => {
    const captured = captureXCallback(
      `http://localhost:3000/connections/x/callback?q=keep&code=secret-code&state=${state}&scope=private#section`,
    )!;
    expect(captured.cleanUrl).toBe("/connections/x/callback?q=keep#section");
    sessionStorage.setItem(
      X_CONSENT_KEY,
      JSON.stringify({
        uid: "owner",
        workspace,
        consent: consentId,
        state,
        expires: Date.now() + 60000,
      }),
    );
    expect(
      consumeXConsent(sessionStorage, captured.callback, "owner", workspace)
        .consent,
    ).toBe(consentId);
    expect(sessionStorage.getItem(X_CONSENT_KEY)).toBeNull();
    sessionStorage.setItem(
      X_CONSENT_KEY,
      JSON.stringify({
        uid: "owner",
        workspace,
        consent: consentId,
        state,
        expires: Date.now() + 60000,
      }),
    );
    expect(() =>
      consumeXConsent(
        sessionStorage,
        captured.callback,
        "another-user",
        workspace,
      ),
    ).toThrow(/Connect again/);
  });
  it("rejects duplicate, denied, and malformed callback values", () => {
    for (const href of [
      `http://localhost/callback?code=a&code=b&state=${state}`,
      `http://localhost/callback?error=access_denied&state=${state}`,
      "http://localhost/callback?code=a&state=short",
    ]) {
      const captured = captureXCallback(href)!;
      expect(captured.callback.invalid || captured.callback.denied).toBe(true);
    }
  });
  it("uses bearer auth, no-store requests, and never accepts token-bearing metadata", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json([metadata]));
    const api = createApi("http://test", fetcher, async () => "app-token");
    await expect(api.xConsents(workspace)).resolves.toEqual([metadata]);
    const [, init] = fetcher.mock.calls[0];
    expect(init.headers.get("Authorization")).toBe("Bearer app-token");
    expect(init.cache).toBe("no-store");
    const malformed = createApi(
      "http://test",
      vi
        .fn()
        .mockResolvedValue(
          Response.json([{ ...metadata, access_token: "private-sentinel" }]),
        ),
    );
    await expect(malformed.xConsents(workspace)).rejects.toThrow(
      /Unexpected X connection/,
    );
  });
  it("keeps consent codes in the request body and treats disconnect as a bodyless 204", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }));
    const api = createApi("http://test", fetcher, async () => "app-token");
    await expect(api.xRevoke(workspace, consentId)).resolves.toBeUndefined();
    const [url, init] = fetcher.mock.calls[0];
    expect(url).not.toContain("private-code");
    expect(init.method).toBe("POST");
    const direct = createXClient(async (_path, request) => {
      expect(request?.body).toContain("private-code");
      return connection;
    });
    await direct.xComplete(workspace, consentId, state, "private-code");
  });
  it("matches native connection receipts to workspace and rejects consent-list or secret-bearing receipts", async () => {
    for (const value of [
      metadata,
      { ...connection, workspace_id: consentId },
      { ...connection, access_token: "private-sentinel" },
      { ...connection, source: "reddit" },
      { ...connection, expires_at: "2000-01-01T00:00:00Z" },
    ]) {
      const client = createXClient(async () => value);
      await expect(
        client.xComplete(workspace, consentId, state, "code"),
      ).rejects.toThrow("Unexpected X connection");
      await expect(client.xRefresh(workspace, consentId)).rejects.toThrow(
        "Unexpected X connection",
      );
    }
    const client = createXClient(async () => connection);
    await expect(client.xRefresh(workspace, consentId)).resolves.toEqual(
      connection,
    );
  });
  it("does not send a request if the identity-scoped operation was aborted during token lookup", async () => {
    let finishToken!: (token: string) => void;
    const fetcher = vi.fn();
    const api = createApi(
      "http://test",
      fetcher,
      () =>
        new Promise((resolve) => {
          finishToken = resolve;
        }),
    );
    const controller = new AbortController();
    const pending = api.xConsents(workspace, controller.signal);
    controller.abort();
    finishToken("new-account-token");
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(fetcher).not.toHaveBeenCalled();
  });
});
