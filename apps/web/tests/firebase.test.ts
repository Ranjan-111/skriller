// @vitest-environment node
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const mock = vi.hoisted(() => ({
  getApps: vi.fn(),
  initializeApp: vi.fn(),
  initializeAuth: vi.fn(),
  observe: vi.fn(),
  popup: vi.fn(),
  signOut: vi.fn(),
  custom: vi.fn(),
  getIdToken: vi.fn(),
  ready: vi.fn(),
}));
vi.mock("firebase/app", () => ({
  getApps: mock.getApps,
  initializeApp: mock.initializeApp,
}));
vi.mock("firebase/auth", () => ({
  browserSessionPersistence: "session",
  browserPopupRedirectResolver: "popup-resolver",
  initializeAuth: mock.initializeAuth,
  onIdTokenChanged: mock.observe,
  signInWithPopup: mock.popup,
  signOut: mock.signOut,
  GoogleAuthProvider: class {
    setCustomParameters = mock.custom;
  },
}));
beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  for (const key of ["API_KEY", "AUTH_DOMAIN", "PROJECT_ID", "APP_ID"])
    vi.stubEnv(`NEXT_PUBLIC_FIREBASE_${key}`, `public-${key.toLowerCase()}`);
  mock.getApps.mockReturnValue([]);
  mock.initializeApp.mockReturnValue({ name: "skriller-browser" });
  mock.getIdToken.mockResolvedValue("test-sdk-token");
  mock.ready.mockResolvedValue(undefined);
  mock.initializeAuth.mockReturnValue({
    currentUser: { getIdToken: mock.getIdToken },
    authStateReady: mock.ready,
  });
});
afterEach(() => vi.unstubAllEnvs());
it("missing public config never initializes Firebase or produces a demo token", async () => {
  vi.stubEnv("NEXT_PUBLIC_FIREBASE_PROJECT_ID", "");
  const { firebaseIdentity } = await import("../src/lib/firebase");
  expect(firebaseIdentity.configured()).toBe(false);
  await expect(firebaseIdentity.getToken()).rejects.toThrow("not configured");
  expect(mock.initializeApp).not.toHaveBeenCalled();
  expect(mock.initializeAuth).not.toHaveBeenCalled();
});
it("uses the official SDK session persistence and forwards forced token refresh", async () => {
  const { firebaseIdentity } = await import("../src/lib/firebase");
  expect(await firebaseIdentity.getToken(true)).toBe("test-sdk-token");
  expect(mock.initializeAuth).toHaveBeenCalledWith(
    { name: "skriller-browser" },
    { persistence: "session", popupRedirectResolver: "popup-resolver" },
  );
  expect(mock.getIdToken).toHaveBeenCalledWith(true);
  expect(mock.ready).toHaveBeenCalledTimes(1);
});
it("explicit Google popup uses account selection and SDK sign out", async () => {
  const { firebaseIdentity } = await import("../src/lib/firebase");
  await firebaseIdentity.signIn();
  await firebaseIdentity.signOut();
  expect(mock.custom).toHaveBeenCalledWith({ prompt: "select_account" });
  expect(mock.popup).toHaveBeenCalledTimes(1);
  expect(mock.signOut).toHaveBeenCalledTimes(1);
});
it("observers expose identity only and never place ID tokens into React state", async () => {
  mock.observe.mockImplementation((_auth, callback) => {
    callback({
      uid: "u1",
      email: "member@example.test",
      accessToken: "secret-token",
    });
    return vi.fn();
  });
  const { firebaseIdentity } = await import("../src/lib/firebase");
  const listener = vi.fn();
  firebaseIdentity.observe(listener);
  expect(listener).toHaveBeenCalledWith({
    uid: "u1",
    email: "member@example.test",
  });
});
