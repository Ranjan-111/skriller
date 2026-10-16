export const CONSENT_KEY = "skriller.youtube-analytics.consent.v1";
export type ConsentIntent = {
  uid: string;
  workspace: string;
  grant: string;
  state: string;
  expires: number;
};
export type ConsentCallback = {
  code: string | null;
  state: string | null;
  denied: boolean;
  invalid: boolean;
};

export function captureCallback(href: string) {
  const url = new URL(href);
  if (!["code", "state", "error"].some((key) => url.searchParams.has(key)))
    return null;
  const code = url.searchParams.get("code"),
    state = url.searchParams.get("state");
  const callback: ConsentCallback = {
    code,
    state,
    denied: url.searchParams.has("error"),
    invalid:
      url.searchParams.getAll("code").length !== 1 ||
      url.searchParams.getAll("state").length !== 1 ||
      !code ||
      code.length > 8192 ||
      !state ||
      !/^[A-Za-z0-9_-]{32,128}$/.test(state),
  };
  for (const key of [
    "code",
    "state",
    "error",
    "error_description",
    "scope",
    "authuser",
    "prompt",
    "hd",
  ])
    url.searchParams.delete(key);
  return { callback, cleanUrl: url.pathname + url.search + url.hash };
}

export function consumeConsent(
  storage: Pick<Storage, "getItem" | "removeItem">,
  callback: ConsentCallback,
  uid: string,
  workspace: string,
): ConsentIntent {
  let intent: ConsentIntent;
  try {
    const raw = storage.getItem(CONSENT_KEY);
    storage.removeItem(CONSENT_KEY); // Single-use even after a context mismatch or denial.
    intent = JSON.parse(raw || "null");
    if (
      !intent ||
      callback.denied ||
      callback.invalid ||
      !callback.code ||
      intent.uid !== uid ||
      intent.workspace !== workspace ||
      intent.state !== callback.state ||
      !/^[0-9a-f-]{36}$/i.test(intent.grant) ||
      !Number.isFinite(intent.expires) ||
      intent.expires <= Date.now()
    )
      throw new Error();
  } catch {
    throw new Error(
      "Analytics consent expired, was declined, or belongs to another account or workspace. Connect again.",
    );
  }
  return intent;
}
