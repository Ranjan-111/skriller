import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { IdentityControls, IdentityProvider } from "../src/components/identity";
const mock = vi.hoisted(() => ({
  configured: vi.fn(),
  observe: vi.fn(),
  signIn: vi.fn(),
  signOut: vi.fn(),
  getToken: vi.fn(),
}));
vi.mock("../src/lib/firebase", () => ({ firebaseIdentity: mock }));
beforeEach(() => {
  vi.clearAllMocks();
  mock.configured.mockReturnValue(true);
  mock.signIn.mockResolvedValue(undefined);
  mock.signOut.mockResolvedValue(undefined);
});
it("shows missing setup without invoking SDK or providing demo identity", async () => {
  mock.configured.mockReturnValue(false);
  render(
    <IdentityProvider>
      <IdentityControls />
    </IdentityProvider>,
  );
  expect(await screen.findByText(/Firebase setup required/)).toBeVisible();
  expect(mock.observe).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("button", { name: "Sign in with Google" }),
  ).not.toBeInTheDocument();
});
it("uses observed identity, explicit sign-in and sign-out, and unsubscribes", async () => {
  let listener: (
    user: { uid: string; email: string } | null,
  ) => void = () => {};
  const unsubscribe = vi.fn();
  mock.observe.mockImplementation((callback) => {
    listener = callback;
    callback(null);
    return unsubscribe;
  });
  const view = render(
    <IdentityProvider>
      <IdentityControls />
    </IdentityProvider>,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Sign in with Google" }),
  );
  await waitFor(() => expect(mock.signIn).toHaveBeenCalledTimes(1));
  await act(async () =>
    listener({ uid: "test-uid", email: "member@example.test" }),
  );
  expect(screen.getByText("member@example.test")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
  await waitFor(() => expect(mock.signOut).toHaveBeenCalledTimes(1));
  await act(async () => listener(null));
  expect(
    screen.getByRole("button", { name: "Sign in with Google" }),
  ).toBeVisible();
  view.unmount();
  expect(unsubscribe).toHaveBeenCalledTimes(1);
});
it("redacts SDK error details and offers retry after popup failure", async () => {
  mock.observe.mockImplementation((callback) => {
    callback(null);
    return vi.fn();
  });
  mock.signIn.mockRejectedValue(new Error("credential-secret raw-sdk-error"));
  render(
    <IdentityProvider>
      <IdentityControls />
    </IdentityProvider>,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Sign in with Google" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Allow the popup and try again",
  );
  expect(screen.queryByText(/credential-secret/)).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Sign in with Google" }),
  ).toBeEnabled();
});
