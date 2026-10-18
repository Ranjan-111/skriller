import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { XConnectionPanel } from "../src/components/x-connection-panel";
import { RedditConnectionPanel } from "../src/components/reddit-connection-panel";
import { createApi } from "../src/lib/api";
import { X_CONSENT_KEY } from "../src/lib/x-oauth";
import { REDDIT_CONSENT_KEY } from "../src/lib/reddit-oauth";

afterEach(() => sessionStorage.clear());

describe.each([
  ["X", XConnectionPanel],
  ["Reddit", RedditConnectionPanel],
] as const)("%s consent account fence", (source, Panel) => {
  it("does not store consent or navigate after the identity changes during start", async () => {
    let finish!: (value: {
      consent_id: string;
      authorization_url: string;
      expires_at: string;
    }) => void;
    const start = vi.fn(
      () =>
        new Promise<Parameters<typeof finish>[0]>((resolve) => {
          finish = resolve;
        }),
    );
    const api = {
      ...createApi("http://test", vi.fn()),
      allowance: vi.fn().mockResolvedValue({
        workspace_id: "22222222-2222-4222-8222-222222222222",
        can_manage: true,
      }),
      xConsents: vi.fn().mockResolvedValue([]),
      redditConsents: vi.fn().mockResolvedValue([]),
      xStart: start,
      redditStart: start,
    };
    const navigate = vi.fn();
    const view = render(
      <Panel
        api={api}
        userId="owner"
        identityStatus="signed_in"
        navigate={navigate}
      />,
    );
    fireEvent.click(
      screen.getByText(
        source === "X" ? "X connection" : "Reddit direct access",
      ),
    );
    await screen.findByText(`No ${source} account is connected.`);
    fireEvent.click(screen.getByRole("button", { name: `Connect ${source}` }));
    await waitFor(() => expect(start).toHaveBeenCalledOnce());
    view.rerender(
      <Panel
        api={api}
        userId="another-account"
        identityStatus="signed_in"
        navigate={navigate}
      />,
    );
    await act(async () => {
      finish({
        consent_id: "11111111-1111-4111-8111-111111111111",
        authorization_url: "https://invalid.example/should-never-open",
        expires_at: "2099-01-01T00:00:00Z",
      });
    });
    expect(navigate).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(X_CONSENT_KEY)).toBeNull();
    expect(sessionStorage.getItem(REDDIT_CONSENT_KEY)).toBeNull();
  });
});
