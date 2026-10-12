"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { firebaseIdentity, type AppIdentity } from "../lib/firebase";

export type IdentityState = {
  status: "loading" | "unavailable" | "signed_out" | "signed_in";
  user: AppIdentity | null;
  pending: boolean;
  error: string;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
  getToken: (forceRefresh?: boolean) => Promise<string | null>;
};
const unavailable = async () => {
  throw new Error("App sign-in is not configured.");
};
const IdentityContext = createContext<IdentityState>({
  status: "unavailable",
  user: null,
  pending: false,
  error: "",
  signIn: unavailable,
  signOut: unavailable,
  getToken: async () => null,
});
export const useIdentity = () => useContext(IdentityContext);

export function IdentityProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<IdentityState["status"]>("loading");
  const [user, setUser] = useState<AppIdentity | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!firebaseIdentity.configured()) {
      setStatus("unavailable");
      return;
    }
    try {
      return firebaseIdentity.observe((identity) => {
        setUser(identity);
        setStatus(identity ? "signed_in" : "signed_out");
      });
    } catch {
      setStatus("unavailable");
      setError(
        "App sign-in could not initialise. Check the local Firebase configuration.",
      );
    }
  }, []);
  async function action(kind: "signIn" | "signOut") {
    setPending(true);
    setError("");
    try {
      await firebaseIdentity[kind]();
    } catch {
      setError(
        kind === "signIn"
          ? "Sign-in did not finish. Allow the popup and try again."
          : "Sign-out did not finish. Try again.",
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <IdentityContext.Provider
      value={{
        status,
        user,
        pending,
        error,
        signIn: () => action("signIn"),
        signOut: () => action("signOut"),
        getToken: (force) => firebaseIdentity.getToken(force),
      }}
    >
      {children}
    </IdentityContext.Provider>
  );
}

export function IdentityControls({ disabled = false }: { disabled?: boolean }) {
  const identity = useIdentity();
  return (
    <div className="identity-controls" aria-label="App account">
      {identity.status === "unavailable" ? (
        <span>App sign-in unavailable · Firebase setup required</span>
      ) : identity.status === "loading" ? (
        <span role="status">Checking sign-in…</span>
      ) : (
        <>
          {identity.user && (
            <span className="identity-name">
              {identity.user.email || "Signed in"}
            </span>
          )}
          <button
            className="account-button"
            disabled={disabled || identity.pending}
            onClick={() =>
              void (identity.status === "signed_in"
                ? identity.signOut()
                : identity.signIn())
            }
          >
            {identity.pending
              ? "Please wait…"
              : identity.status === "signed_in"
                ? "Sign out"
                : "Sign in with Google"}
          </button>
        </>
      )}
      {identity.error && (
        <p className="identity-error" role="alert">
          {identity.error}
        </p>
      )}
    </div>
  );
}
