import { getApps, initializeApp, type FirebaseOptions } from "firebase/app";
import {
  browserPopupRedirectResolver,
  browserSessionPersistence,
  GoogleAuthProvider,
  initializeAuth,
  onIdTokenChanged,
  signInWithPopup,
  signOut,
  type Auth,
  type User,
} from "firebase/auth";

export type AppIdentity = Pick<User, "uid" | "email">;
const appName = "skriller-browser";
let auth: Auth | null = null;

export function publicFirebaseConfig(): FirebaseOptions | null {
  const config = {
    apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
    authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
    projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
    appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
  };
  return Object.values(config).every(
    (value) => typeof value === "string" && value.trim(),
  )
    ? config
    : null;
}
function browserAuth(): Auth {
  const config = publicFirebaseConfig();
  if (!config) throw new Error("App sign-in is not configured.");
  if (!auth) {
    const app =
      getApps().find((app) => app.name === appName) ??
      initializeApp(config, appName);
    auth = initializeAuth(app, {
      persistence: browserSessionPersistence,
      popupRedirectResolver: browserPopupRedirectResolver,
    });
  }
  return auth;
}

export const firebaseIdentity = {
  configured: () => publicFirebaseConfig() !== null,
  observe(listener: (identity: AppIdentity | null) => void): () => void {
    return onIdTokenChanged(browserAuth(), (user) =>
      listener(user ? { uid: user.uid, email: user.email } : null),
    );
  },
  async getToken(forceRefresh = false): Promise<string | null> {
    const current = browserAuth();
    await current.authStateReady();
    return current.currentUser
      ? current.currentUser.getIdToken(forceRefresh)
      : null;
  },
  async signIn(): Promise<void> {
    const provider = new GoogleAuthProvider();
    provider.setCustomParameters({ prompt: "select_account" });
    await signInWithPopup(browserAuth(), provider);
  },
  async signOut(): Promise<void> {
    await signOut(browserAuth());
  },
};
