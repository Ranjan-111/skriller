import { StrictMode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { XConnectionPanel } from "../src/components/x-connection-panel";
import { createApi } from "../src/lib/api";
import { X_CONSENT_KEY, type XConsentMetadata } from "../src/lib/x-oauth";

const workspace = "22222222-2222-4222-8222-222222222222";
const consentId = "11111111-1111-4111-8111-111111111111";
const connectionId = "33333333-3333-4333-8333-333333333333";
const state = "s".repeat(43);
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
const authorization = new URL("https://x.com/i/oauth2/authorize");
for (const [key, value] of Object.entries({
  response_type: "code",
  client_id: "public-client",
  redirect_uri: "http://localhost:3000/connections/x/callback",
  scope: "tweet.read users.read offline.access",
  state,
  code_challenge: "c".repeat(43),
  code_challenge_method: "S256",
}))
  authorization.searchParams.set(key, value);
function client(owner = true, rows: XConsentMetadata[] = []) {
  return {
    ...createApi("http://test", vi.fn()),
    allowance: vi
      .fn()
      .mockResolvedValue({ workspace_id: workspace, can_manage: owner }),
    xConsents: vi.fn().mockResolvedValue(rows),
    xStart: vi.fn().mockResolvedValue({
      consent_id: consentId,
      authorization_url: authorization.href,
      expires_at: "2099-01-01T00:00:00Z",
    }),
    xComplete: vi.fn().mockResolvedValue(connection),
    xRefresh: vi.fn().mockResolvedValue({
      ...connection,
      id: "44444444-4444-4444-8444-444444444444",
    }),
    xRevoke: vi.fn().mockResolvedValue(undefined),
  };
}
afterEach(() => {
  sessionStorage.clear();
  window.history.replaceState(null, "", "/");
});

describe("X owner connection panel", () => {
  it("starts only on explicit connect and stores only a short-lived one-use consent intent", async () => {
    const api = client(),
      navigate = vi.fn();
    render(
      <XConnectionPanel
        api={api}
        userId="owner"
        identityStatus="signed_in"
        navigate={navigate}
      />,
    );
    fireEvent.click(screen.getByText("X connection"));
    await screen.findByText("No X account is connected.");
    fireEvent.click(screen.getByRole("button", { name: "Connect X" }));
    await waitFor(() =>
      expect(navigate).toHaveBeenCalledWith(authorization.href),
    );
    expect(api.xStart).toHaveBeenCalledWith(workspace, expect.any(AbortSignal));
    const intent = JSON.parse(sessionStorage.getItem(X_CONSENT_KEY)!);
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
  it("cleans and completes the callback once after signed-in workspace context is ready", async () => {
    const api = client();
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
    window.history.replaceState(
      null,
      "",
      `/connections/x/callback?code=private-code&state=${state}&scope=private`,
    );
    const view = render(
      <StrictMode>
        <XConnectionPanel api={api} identityStatus="loading" />
      </StrictMode>,
    );
    expect(window.location.search).toBe("");
    expect(api.xComplete).not.toHaveBeenCalled();
    view.rerender(
      <StrictMode>
        <XConnectionPanel api={api} userId="owner" identityStatus="signed_in" />
      </StrictMode>,
    );
    await waitFor(() =>
      expect(api.xComplete).toHaveBeenCalledExactlyOnceWith(
        workspace,
        consentId,
        state,
        "private-code",
        expect.any(AbortSignal),
      ),
    );
    expect(sessionStorage.getItem(X_CONSENT_KEY)).toBeNull();
  });
  it("keeps connection state owner-only and exposes that local disconnect is not remote revocation", async () => {
    const api = client(false, [metadata]);
    render(
      <XConnectionPanel api={api} userId="member" identityStatus="signed_in" />,
    );
    fireEvent.click(screen.getByText("X connection"));
    expect(
      await screen.findByText(/Only the workspace owner can connect X/),
    ).toBeVisible();
    expect(api.xConsents).not.toHaveBeenCalled();
    const ownerApi = client(true, [metadata]);
    const connected = vi.fn();
    render(
      <XConnectionPanel
        api={ownerApi}
        userId="owner"
        identityStatus="signed_in"
        onConnectedChange={connected}
      />,
    );
    fireEvent.click(screen.getAllByText("X connection")[1]);
    fireEvent.click(
      await screen.findByRole("button", { name: "Disconnect locally" }),
    );
    await waitFor(() =>
      expect(ownerApi.xRevoke).toHaveBeenCalledWith(
        workspace,
        consentId,
        expect.any(AbortSignal),
      ),
    );
    expect(
      await screen.findByText(/does not revoke the grant at X/),
    ).toBeVisible();
    expect(connected).toHaveBeenCalledWith(true);
  });
});
