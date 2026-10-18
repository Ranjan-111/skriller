export type BillingProvider = "stripe" | "razorpay";
export type BillingPlan = "starter" | "pro";
export type CheckoutState = "dispatching" | "ready" | "uncertain" | "bound";

export type CheckoutOffer = {
  provider: BillingProvider;
  plan: BillingPlan;
  amount_minor: number;
  currency: "USD" | "INR";
  interval: "month";
  maximum_monthly_cycles: number | null;
  runs_per_month: number;
  results_per_run: number;
  sources_per_run: number;
  configured: boolean;
};
export type CheckoutOutput = {
  id: string;
  provider: BillingProvider;
  plan: BillingPlan;
  state: CheckoutState;
  expires_at: string;
  checkout_url: string | null;
  maximum_monthly_cycles: number | null;
};
export type CheckoutCatalog = {
  can_start: boolean;
  offers: CheckoutOffer[];
  current: CheckoutOutput | null;
};

export class BillingApiError extends Error {
  constructor(
    message: string,
    public status?: number,
  ) {
    super(message);
    this.name = "BillingApiError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}
function validOffer(value: unknown): value is CheckoutOffer {
  if (!isRecord(value)) return false;
  return (
    ["stripe", "razorpay"].includes(String(value.provider)) &&
    ["starter", "pro"].includes(String(value.plan)) &&
    Number.isSafeInteger(value.amount_minor) &&
    Number(value.amount_minor) > 0 &&
    ["USD", "INR"].includes(String(value.currency)) &&
    value.interval === "month" &&
    (value.maximum_monthly_cycles === null ||
      (Number.isSafeInteger(value.maximum_monthly_cycles) &&
        Number(value.maximum_monthly_cycles) > 0)) &&
    Number.isSafeInteger(value.runs_per_month) &&
    Number(value.runs_per_month) > 0 &&
    Number.isSafeInteger(value.results_per_run) &&
    Number(value.results_per_run) > 0 &&
    Number.isSafeInteger(value.sources_per_run) &&
    Number(value.sources_per_run) > 0 &&
    typeof value.configured === "boolean"
  );
}
function validCheckout(value: unknown): value is CheckoutOutput {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    /^[0-9a-f-]{36}$/i.test(value.id) &&
    ["stripe", "razorpay"].includes(String(value.provider)) &&
    ["starter", "pro"].includes(String(value.plan)) &&
    ["dispatching", "ready", "uncertain", "bound"].includes(
      String(value.state),
    ) &&
    typeof value.expires_at === "string" &&
    Number.isFinite(Date.parse(value.expires_at)) &&
    (value.checkout_url === null || typeof value.checkout_url === "string") &&
    (value.maximum_monthly_cycles === null ||
      (Number.isSafeInteger(value.maximum_monthly_cycles) &&
        Number(value.maximum_monthly_cycles) > 0))
  );
}
function validCatalog(value: unknown): value is CheckoutCatalog {
  return (
    isRecord(value) &&
    typeof value.can_start === "boolean" &&
    Array.isArray(value.offers) &&
    value.offers.length <= 10 &&
    value.offers.every(validOffer) &&
    (value.current === null || validCheckout(value.current))
  );
}
function safeCheckoutUrl(output: CheckoutOutput): string | null {
  if (output.state !== "ready" || Date.parse(output.expires_at) <= Date.now())
    return null;
  if (!output.checkout_url || output.checkout_url.length > 4096) return null;
  try {
    const url = new URL(output.checkout_url);
    const allowed =
      (output.provider === "stripe" &&
        url.hostname === "checkout.stripe.com") ||
      (output.provider === "razorpay" && url.hostname === "rzp.io");
    if (
      url.protocol !== "https:" ||
      !allowed ||
      url.username ||
      url.password ||
      url.port
    )
      return null;
    return url.href;
  } catch {
    return null;
  }
}

export function createBillingClient(
  baseUrl = process.env.NEXT_PUBLIC_BILLING_API_URL || "",
  getToken: (forceRefresh?: boolean) => Promise<string | null>,
  fetcher: typeof fetch = fetch,
) {
  const base = baseUrl.trim().replace(/\/$/, "");
  async function request(path: string, init?: RequestInit): Promise<unknown> {
    if (!base) throw new BillingApiError("Billing is not configured yet.");
    let token: string | null;
    try {
      token = await getToken();
    } catch {
      throw new BillingApiError("Sign in again before managing billing.", 401);
    }
    if (!token)
      throw new BillingApiError("Sign in again before managing billing.", 401);
    init?.signal?.throwIfAborted();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetcher(`${base}${path}`, {
        ...init,
        headers: new Headers({
          Authorization: `Bearer ${token}`,
          ...(init?.body ? { "Content-Type": "application/json" } : {}),
          ...Object.fromEntries(new Headers(init?.headers).entries()),
        }),
        signal: init?.signal
          ? AbortSignal.any([controller.signal, init.signal])
          : controller.signal,
        cache: "no-store",
        credentials: "omit",
        redirect: "error",
      });
      if (response.status === 401)
        throw new BillingApiError(
          "Sign in again before managing billing.",
          401,
        );
      if (response.status === 403)
        throw new BillingApiError(
          "Only the workspace owner can manage billing.",
          403,
        );
      if (response.status === 409)
        throw new BillingApiError(
          "A checkout already exists or needs operator review. Refresh its status before taking another action.",
          409,
        );
      if (!response.ok)
        throw new BillingApiError(
          response.status === 503
            ? "Billing is not configured for this workspace yet."
            : "Billing could not be loaded. Try again.",
          response.status,
        );
      try {
        return await response.json();
      } catch {
        throw new BillingApiError("Billing returned an unexpected response.");
      }
    } catch (error) {
      if (error instanceof BillingApiError) throw error;
      throw new BillingApiError(
        error instanceof Error && error.name === "AbortError"
          ? "Billing took too long to respond. Refresh and try again."
          : "The billing service could not be reached. Try again.",
      );
    } finally {
      clearTimeout(timer);
    }
  }
  function workspacePath(workspaceId: string) {
    return `/v1/workspaces/${encodeURIComponent(workspaceId)}/checkout`;
  }
  return {
    enabled: Boolean(base),
    async catalog(
      workspaceId: string,
      signal?: AbortSignal,
    ): Promise<CheckoutCatalog> {
      const data = await request(workspacePath(workspaceId), { signal });
      if (!validCatalog(data))
        throw new BillingApiError("Billing returned an invalid offer list.");
      return data;
    },
    async start(
      workspaceId: string,
      provider: BillingProvider,
      plan: BillingPlan,
      idempotencyKey: string,
      signal?: AbortSignal,
    ): Promise<CheckoutOutput> {
      const data = await request(workspacePath(workspaceId), {
        method: "POST",
        signal,
        body: JSON.stringify({
          provider,
          plan,
          idempotency_key: idempotencyKey,
          opt_in: true,
        }),
      });
      if (
        !validCheckout(data) ||
        data.provider !== provider ||
        data.plan !== plan
      )
        throw new BillingApiError("Billing returned an invalid checkout.");
      return data;
    },
    async status(
      workspaceId: string,
      checkoutId: string,
      signal?: AbortSignal,
    ): Promise<CheckoutOutput> {
      const data = await request(
        `${workspacePath(workspaceId)}/${encodeURIComponent(checkoutId)}`,
        { signal },
      );
      if (!validCheckout(data) || data.id !== checkoutId)
        throw new BillingApiError(
          "Billing returned an invalid checkout status.",
        );
      return data;
    },
  };
}

export function checkoutLink(output: CheckoutOutput): string | null {
  return safeCheckoutUrl(output);
}

export function checkoutIdempotencyKey(
  workspaceId: string,
  provider: BillingProvider,
  plan: BillingPlan,
): string {
  // This stable, non-secret key lets retries reuse the one permitted initial intent.
  return `skriller_${workspaceId}_${provider}_${plan}`;
}
