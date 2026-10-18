import { describe, expect, it, vi } from "vitest";
import { createApi } from "../src/lib/api";
import {
  captureRedditCallback,
  consumeRedditConsent,
  createRedditClient,
  REDDIT_CONSENT_KEY,
  redditConsentState,
  type RedditConsentMetadata,
} from "../src/lib/reddit-oauth";

const workspace = "22222222-2222-4222-8222-222222222222";
const consentId = "11111111-1111-4111-8111-111111111111";
const connectionId = "33333333-3333-4333-8333-333333333333";
const state = "s".repeat(43);

function authorizationUrl(overrides: Record<string, string> = {}) {
  const url = new URL("https://www.reddit.com/api/v1/authorize");
  Object.entries({
    response_type: "code",
    client_id: "public-client",
    redirect_uri: "http://localhost:3000/connections/reddit/callback",
    scope: "read",
    state,
    duration: "permanent",
    ...overrides,
  }).forEach(([key, value]) => url.searchParams.set(key, value));
  return url.href;
}

const connection = {
  id: connectionId,
  workspace_id: workspace,
  source: "reddit" as const,
  auth_kind: "oauth" as const,
  scopes: ["read", "discover"],
  state: "active" as const,
  expires_at: "2099-01-01T00:00:00Z",
  access_validation: "not_performed" as const,
  remote_revocation: "not_performed" as const,
};
const metadata: RedditConsentMetadata = {
  consent_id: consentId,
  connection_id: connectionId,
  state: "active",
  expires_at: "2099-01-01T00:00:00Z",
  access_expires_at: "2099-01-01T00:00:00Z",
  access_state: "active",
  remote_revocation: "not_performed",
};

describe("Reddit OAuth client contracts", () => {
  it("accepts only Reddit's fixed read-only permanent authorization request", () => {
    expect(
      redditConsentState(
        {
          consent_id: consentId,
          authorization_url: authorizationUrl(),
          expires_at: "2099-01-01T00:00:00Z",
        },
        "http://localhost:3000",
      ),
    ).toBe(state);
    for (const url of [
      authorizationUrl({ scope: "read identity" }),
      authorizationUrl({ duration: "temporary" }),
      authorizationUrl({ redirect_uri: "https://evil.example/callback" }),
      `${authorizationUrl()}&state=${state}`,
      `${authorizationUrl()}&code_challenge=secret`,
      `${authorizationUrl()}#unexpected`,
      authorizationUrl().replace(
        "https://www.reddit.com",
        "https://user:password@www.reddit.com",
      ),
      authorizationUrl().replace(
        "https://www.reddit.com",
        "https://evil.example",
      ),
    ]) {
      expect(() =>
        redditConsentState(
          {
            consent_id: consentId,
            authorization_url: url,
            expires_at: "2099-01-01T00:00:00Z",
          },
          "http://localhost:3000",
        ),
      ).toThrow(/Reddit consent response is invalid/);
    }
  });

  it("cleans provider values before auth and consumes account-bound intent once", () => {
    const captured = captureRedditCallback(
      `http://localhost:3000/connections/reddit/callback?q=keep&code=private-code&state=${state}&scope=read#section`,
    )!;
    expect(captured.cleanUrl).toBe(
      "/connections/reddit/callback?q=keep#section",
    );
    sessionStorage.setItem(
      REDDIT_CONSENT_KEY,
      JSON.stringify({
        uid: "owner",
        workspace,
        consent: consentId,
        state,
        expires: Date.now() + 60_000,
      }),
    );
    expect(
      consumeRedditConsent(
        sessionStorage,
        captured.callback,
        "owner",
        workspace,
      ).consent,
    ).toBe(consentId);
    expect(sessionStorage.getItem(REDDIT_CONSENT_KEY)).toBeNull();
    sessionStorage.setItem(
      REDDIT_CONSENT_KEY,
      JSON.stringify({
        uid: "owner",
        workspace,
        consent: consentId,
        state,
        expires: Date.now() + 60_000,
      }),
    );
    expect(() =>
      consumeRedditConsent(
        sessionStorage,
        captured.callback,
        "another-user",
        workspace,
      ),
    ).toThrow(/Connect again/);
  });

  it("rejects duplicate, denied, and malformed callbacks", () => {
    for (const href of [
      `http://localhost/callback?code=a&code=b&state=${state}`,
      `http://localhost/callback?error=access_denied&state=${state}`,
      "http://localhost/callback?code=a&state=short",
    ]) {
      const captured = captureRedditCallback(href)!;
      expect(captured.callback.invalid || captured.callback.denied).toBe(true);
    }
  });

  it("uses bearer auth, no-store requests, and rejects token-bearing metadata", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json([metadata]));
    const api = createApi("http://test", fetcher, async () => "app-token");
    await expect(api.redditConsents(workspace)).resolves.toEqual([metadata]);
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
    await expect(malformed.redditConsents(workspace)).rejects.toThrow(
      /Unexpected Reddit connection/,
    );
  });

  it("explains missing server configuration without exposing provider details", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        Response.json(
          { detail: "Reddit authorization is not configured" },
          { status: 503 },
        ),
      );
    const api = createApi("http://test", fetcher, async () => "app-token");
    await expect(api.redditConsents(workspace)).rejects.toThrow(
      /Reddit authorization needs server configuration/,
    );
  });

  it("keeps codes in the request body and treats disconnect as a bodyless 204", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }));
    const api = createApi("http://test", fetcher, async () => "app-token");
    await expect(
      api.redditRevoke(workspace, consentId),
    ).resolves.toBeUndefined();
    const [url, init] = fetcher.mock.calls[0];
    expect(url).not.toContain("private-code");
    expect(init.method).toBe("POST");
    const direct = createRedditClient(async (_path, request) => {
      expect(request?.body).toContain("private-code");
      return connection;
    });
    await direct.redditComplete(workspace, consentId, state, "private-code");
  });

  it("matches receipts to workspace and rejects wrong-source or secret-bearing receipts", async () => {
    for (const value of [
      metadata,
      { ...connection, workspace_id: consentId },
      { ...connection, access_token: "private-sentinel" },
      { ...connection, source: "x" },
      { ...connection, expires_at: "2000-01-01T00:00:00Z" },
    ]) {
      const client = createRedditClient(async () => value);
      await expect(
        client.redditComplete(workspace, consentId, state, "code"),
      ).rejects.toThrow("Unexpected Reddit connection");
      await expect(client.redditRefresh(workspace, consentId)).rejects.toThrow(
        "Unexpected Reddit connection",
      );
    }
    const client = createRedditClient(async () => connection);
    await expect(client.redditRefresh(workspace, consentId)).resolves.toEqual(
      connection,
    );
  });

  it("does not send after an identity-scoped operation is aborted during token lookup", async () => {
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
    const pending = api.redditConsents(workspace, controller.signal);
    controller.abort();
    finishToken("new-account-token");
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(fetcher).not.toHaveBeenCalled();
  });
});
