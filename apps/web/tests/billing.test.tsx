import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { createApi } from "../src/lib/api";
import { BillingPanel } from "../src/components/billing-panel";
import {
  checkoutIdempotencyKey,
  checkoutLink,
  createBillingClient,
  type CheckoutCatalog,
} from "../src/lib/billing";

const offer = {
  provider: "stripe" as const,
  plan: "starter" as const,
  amount_minor: 2900,
  currency: "USD" as const,
  interval: "month" as const,
  maximum_monthly_cycles: null,
  runs_per_month: 50,
  results_per_run: 25,
  sources_per_run: 3,
  configured: true,
};
const checkout = {
  id: "11111111-1111-4111-8111-111111111111",
  provider: "stripe" as const,
  plan: "starter" as const,
  state: "ready" as const,
  expires_at: new Date(Date.now() + 60_000).toISOString(),
  checkout_url: "https://checkout.stripe.com/c/pay/cs_test_abc",
  maximum_monthly_cycles: null,
};
const catalog: CheckoutCatalog = {
  can_start: true,
  offers: [offer],
  current: null,
};
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const workspaceApi = {
  allowance: vi.fn().mockResolvedValue({ workspace_id: "w1" }),
} as unknown as ReturnType<typeof createApi>;

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

describe("billing client", () => {
  it("does not send an old workspace request if identity changed during token lookup", async () => {
    let resolveToken!: (value: string) => void;
    const token = new Promise<string>((resolve) => {
      resolveToken = resolve;
    });
    const fetcher = vi.fn();
    const client = createBillingClient(
      "https://billing.example",
      () => token,
      fetcher,
    );
    const controller = new AbortController();
    const pending = client.start(
      "w1",
      "stripe",
      "starter",
      "fixture_checkout_key",
      controller.signal,
    );
    const rejected = expect(pending).rejects.toThrow();
    controller.abort();
    resolveToken("new-account-token");
    await rejected;
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("uses Firebase bearer auth, no cookies, and validates server payloads", async () => {
    const fetcher = vi.fn().mockResolvedValue(response(catalog));
    const client = createBillingClient(
      "https://billing.example",
      async () => "firebase-token",
      fetcher,
    );
    expect(await client.catalog("workspace/one")).toEqual(catalog);
    expect(fetcher).toHaveBeenCalledTimes(1);
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe(
      "https://billing.example/v1/workspaces/workspace%2Fone/checkout",
    );
    expect(init?.credentials).toBe("omit");
    expect(init?.redirect).toBe("error");
    expect(init?.cache).toBe("no-store");
    expect(new Headers(init?.headers).get("Authorization")).toBe(
      "Bearer firebase-token",
    );
  });

  it("uses stable per workspace/provider/plan idempotency keys", () => {
    expect(checkoutIdempotencyKey("w1", "stripe", "pro")).toBe(
      checkoutIdempotencyKey("w1", "stripe", "pro"),
    );
    expect(checkoutIdempotencyKey("w1", "stripe", "pro")).not.toBe(
      checkoutIdempotencyKey("w1", "razorpay", "pro"),
    );
  });

  it("rejects expired, unready, wrong-provider, or unsafe checkout URLs", () => {
    expect(checkoutLink(checkout)).toBe(checkout.checkout_url);
    expect(
      checkoutLink({
        ...checkout,
        state: "uncertain",
        checkout_url: "https://checkout.stripe.com/c/pay/x",
      }),
    ).toBeNull();
    expect(
      checkoutLink({
        ...checkout,
        checkout_url: "https://attacker.example/c/pay/x",
      }),
    ).toBeNull();
    expect(
      checkoutLink({
        ...checkout,
        provider: "razorpay",
        checkout_url: "https://checkout.stripe.com/c/pay/x",
      }),
    ).toBeNull();
    expect(
      checkoutLink({
        ...checkout,
        expires_at: new Date(Date.now() - 60_000).toISOString(),
      }),
    ).toBeNull();
  });
});

describe("billing panel", () => {
  it("removes a ready link at expiry without waiting for a server refresh", async () => {
    vi.useFakeTimers();
    vi.stubEnv("NEXT_PUBLIC_BILLING_API_URL", "https://billing.example");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        response({
          ...catalog,
          can_start: false,
          current: {
            ...checkout,
            expires_at: new Date(Date.now() + 2000).toISOString(),
          },
        }),
      ),
    );
    await act(async () => {
      render(
        <BillingPanel
          api={workspaceApi}
          userId="uid-expiry"
          identityStatus="signed_in"
          getToken={vi.fn().mockResolvedValue("token")}
        />,
      );
    });
    fireEvent.click(screen.getByText("Plans and billing"));
    expect(
      screen.getByRole("link", { name: "Review payment with Stripe" }),
    ).toBeVisible();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2001);
    });
    expect(
      screen.queryByRole("link", { name: "Review payment with Stripe" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/expired or failed validation/)).toBeVisible();
  });

  it("aborts a pending checkout and drops its response when the account changes", async () => {
    vi.stubEnv("NEXT_PUBLIC_BILLING_API_URL", "https://billing.example");
    let resolvePost!: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      resolvePost = resolve;
    });
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(response(catalog))
      .mockReturnValueOnce(pending)
      .mockResolvedValue(response(catalog));
    vi.stubGlobal("fetch", fetcher);
    const token = vi.fn().mockResolvedValue("token");
    const api = {
      allowance: vi
        .fn()
        .mockResolvedValueOnce({ workspace_id: "w1" })
        .mockResolvedValue({ workspace_id: "w2" }),
    } as unknown as ReturnType<typeof createApi>;
    const { rerender } = render(
      <BillingPanel
        api={api}
        userId="old-user"
        identityStatus="signed_in"
        getToken={token}
      />,
    );
    fireEvent.click(screen.getByText("Plans and billing"));
    await screen.findByText("$29/month");
    fireEvent.click(
      screen.getByRole("checkbox", { name: /I want to continue/ }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Continue to checkout" }),
    );
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    const signal = fetcher.mock.calls[1][1].signal;
    rerender(
      <BillingPanel
        api={api}
        userId="new-user"
        identityStatus="signed_in"
        getToken={token}
      />,
    );
    await act(async () => {
      resolvePost(response(checkout));
    });
    expect(signal.aborted).toBe(true);
    expect(
      screen.queryByRole("link", { name: "Review payment with Stripe" }),
    ).not.toBeInTheDocument();
    expect(
      fetcher.mock.calls.filter(([, init]) => init.method === "POST"),
    ).toHaveLength(1);
  });
  it("requires explicit opt-in and posts one stable intent", async () => {
    vi.stubEnv("NEXT_PUBLIC_BILLING_API_URL", "https://billing.example");
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(response(catalog))
      .mockResolvedValueOnce(response(checkout));
    vi.stubGlobal("fetch", fetcher);
    const token = vi.fn().mockResolvedValue("token");
    render(
      <BillingPanel
        api={workspaceApi}
        userId="uid-1"
        identityStatus="signed_in"
        getToken={token}
      />,
    );
    fireEvent.click(screen.getByText("Plans and billing"));
    expect(await screen.findByText("$29/month")).toBeVisible();
    const submit = screen.getByRole("button", { name: "Continue to checkout" });
    expect(submit).toBeDisabled();
    expect(fetcher).toHaveBeenCalledTimes(1);
    fireEvent.click(
      screen.getByRole("checkbox", { name: /I want to continue/ }),
    );
    fireEvent.click(submit);
    expect(
      await screen.findByRole("link", { name: "Review payment with Stripe" }),
    ).toHaveAttribute("href", checkout.checkout_url);
    const post = fetcher.mock.calls[1];
    expect(post[0]).toBe("https://billing.example/v1/workspaces/w1/checkout");
    expect(post[1]?.method).toBe("POST");
    expect(JSON.parse(String(post[1]?.body))).toEqual({
      provider: "stripe",
      plan: "starter",
      idempotency_key: "skriller_w1_stripe_starter",
      opt_in: true,
    });
  });

  it("never offers an extra checkout when a current request is uncertain", async () => {
    vi.stubEnv("NEXT_PUBLIC_BILLING_API_URL", "https://billing.example");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        response({
          ...catalog,
          can_start: false,
          current: { ...checkout, state: "uncertain", checkout_url: null },
        }),
      ),
    );
    render(
      <BillingPanel
        api={workspaceApi}
        userId="uid-1"
        identityStatus="signed_in"
        getToken={vi.fn().mockResolvedValue("token")}
      />,
    );
    fireEvent.click(screen.getByText("Plans and billing"));
    expect(await screen.findByText(/needs operator review/)).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Continue to checkout" }),
    ).not.toBeInTheDocument();
  });

  it("clears its workspace billing view after sign-out", async () => {
    vi.stubEnv("NEXT_PUBLIC_BILLING_API_URL", "https://billing.example");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(catalog)));
    const { rerender } = render(
      <BillingPanel
        api={workspaceApi}
        userId="uid-1"
        identityStatus="signed_in"
        getToken={vi.fn().mockResolvedValue("token")}
      />,
    );
    fireEvent.click(screen.getByText("Plans and billing"));
    expect(await screen.findByText("$29/month")).toBeVisible();
    rerender(
      <BillingPanel
        api={workspaceApi}
        userId={undefined}
        identityStatus="signed_out"
        getToken={vi.fn().mockResolvedValue(null)}
      />,
    );
    await waitFor(() =>
      expect(screen.queryByText("$29/month")).not.toBeInTheDocument(),
    );
  });
});
