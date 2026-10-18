import { StrictMode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RedditConnectionPanel } from "../src/components/reddit-connection-panel";
import { createApi } from "../src/lib/api";
import {
  REDDIT_CONSENT_KEY,
  type RedditConsentMetadata,
} from "../src/lib/reddit-oauth";

const workspace = "22222222-2222-4222-8222-222222222222";
const consentId = "11111111-1111-4111-8111-111111111111";
const connectionId = "33333333-3333-4333-8333-333333333333";
const state = "s".repeat(43);
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
const authorization = new URL("https://www.reddit.com/api/v1/authorize");
for (const [key, value] of Object.entries({
  response_type: "code",
  client_id: "public-client",
  redirect_uri: "http://localhost:3000/connections/reddit/callback",
  scope: "read",
  state,
  duration: "permanent",
}))
  authorization.searchParams.set(key, value);

function client(owner = true, rows: RedditConsentMetadata[] = []) {
  return {
    ...createApi("http://test", vi.fn()),
    allowance: vi
      .fn()
      .mockResolvedValue({ workspace_id: workspace, can_manage: owner }),
    redditConsents: vi.fn().mockResolvedValue(rows),
    redditStart: vi.fn().mockResolvedValue({
      consent_id: consentId,
      authorization_url: authorization.href,
      expires_at: "2099-01-01T00:00:00Z",
    }),
    redditComplete: vi.fn().mockResolvedValue(connection),
    redditRefresh: vi.fn().mockResolvedValue({
      ...connection,
      id: "44444444-4444-4444-8444-444444444444",
    }),
    redditRevoke: vi.fn().mockResolvedValue(undefined),
  };
}

afterEach(() => {
  sessionStorage.clear();
  window.history.replaceState(null, "", "/");
});

describe("Reddit owner connection panel", () => {
  it("reloads connection metadata when a run reports access renewal", async () => {
    const api = client(true, [metadata]);
    const { rerender } = render(
      <RedditConnectionPanel
        api={api}
        userId="owner"
        identityStatus="signed_in"
        refreshKey={0}
      />,
    );
    await screen.findByText(/Connected/);
    api.redditConsents.mockResolvedValue([
      { ...metadata, access_expires_at: "2099-02-01T00:00:00Z" },
    ]);
    rerender(
      <RedditConnectionPanel
        api={api}
        userId="owner"
        identityStatus="signed_in"
        refreshKey={1}
      />,
    );
    await waitFor(() => expect(api.redditConsents).toHaveBeenCalledTimes(2));
    expect(api.redditConsents.mock.calls[1][0]).toBe(workspace);
  });

  it("starts only on explicit connect and stores a short-lived one-use intent", async () => {
    const api = client();
    const navigate = vi.fn();
    render(
      <RedditConnectionPanel
        api={api}
        userId="owner"
        identityStatus="signed_in"
        navigate={navigate}
      />,
    );
    fireEvent.click(screen.getByText("Reddit direct access"));
    await screen.findByText("No Reddit account is connected.");
    fireEvent.click(screen.getByRole("button", { name: "Connect Reddit" }));
    await waitFor(() =>
      expect(navigate).toHaveBeenCalledWith(authorization.href),
    );
    expect(api.redditStart).toHaveBeenCalledWith(
      workspace,
      expect.any(AbortSignal),
    );
    const intent = JSON.parse(sessionStorage.getItem(REDDIT_CONSENT_KEY)!);
    expect(intent).toMatchObject({
      uid: "owner",
      workspace,
      consent: consentId,
      state,
    });
    expect(JSON.stringify(intent)).not.toMatch(
      /access_token|refresh_token|secret/i,
    );
  });

  it("strips the callback immediately and completes it once after identity resolves", async () => {
    const api = client();
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
    window.history.replaceState(
      null,
      "",
      `/connections/reddit/callback?code=private-code&state=${state}&scope=read`,
    );
    const view = render(
      <StrictMode>
        <RedditConnectionPanel api={api} identityStatus="loading" />
      </StrictMode>,
    );
    expect(window.location.search).toBe("");
    expect(api.redditComplete).not.toHaveBeenCalled();
    view.rerender(
      <StrictMode>
        <RedditConnectionPanel
          api={api}
          userId="owner"
          identityStatus="signed_in"
        />
      </StrictMode>,
    );
    await waitFor(() =>
      expect(api.redditComplete).toHaveBeenCalledExactlyOnceWith(
        workspace,
        consentId,
        state,
        "private-code",
        expect.any(AbortSignal),
      ),
    );
    expect(sessionStorage.getItem(REDDIT_CONSENT_KEY)).toBeNull();
  });

  it("keeps management owner-only while explaining indexed search remains available", async () => {
    const api = client(false, [metadata]);
    render(
      <RedditConnectionPanel
        api={api}
        userId="member"
        identityStatus="signed_in"
      />,
    );
    fireEvent.click(screen.getByText("Reddit direct access"));
    expect(
      await screen.findByText(/Only the workspace owner can connect Reddit/),
    ).toBeVisible();
    expect(
      screen.getByText(/Indexed Reddit search remains available/),
    ).toBeVisible();
    expect(api.redditConsents).not.toHaveBeenCalled();
  });

  it("refreshes by replacement and labels disconnect as local-only", async () => {
    const api = client(true, [metadata]);
    render(
      <RedditConnectionPanel
        api={api}
        userId="owner"
        identityStatus="signed_in"
      />,
    );
    fireEvent.click(screen.getByText("Reddit direct access"));
    fireEvent.click(
      await screen.findByRole("button", { name: "Refresh access" }),
    );
    await waitFor(() =>
      expect(api.redditRefresh).toHaveBeenCalledWith(
        workspace,
        consentId,
        expect.any(AbortSignal),
      ),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Disconnect locally" }),
    );
    await waitFor(() =>
      expect(api.redditRevoke).toHaveBeenCalledWith(
        workspace,
        consentId,
        expect.any(AbortSignal),
      ),
    );
    expect(
      screen.getByText(/does not revoke the grant at Reddit/),
    ).toBeVisible();
    expect(screen.getByText(/access expires/)).toHaveTextContent(
      /consent retained until/,
    );
  });
});
