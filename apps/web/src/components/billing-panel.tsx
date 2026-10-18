"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { createApi } from "../lib/api";
import {
  BillingApiError,
  checkoutIdempotencyKey,
  checkoutLink,
  createBillingClient,
  type BillingPlan,
  type BillingProvider,
  type CheckoutCatalog,
  type CheckoutOutput,
} from "../lib/billing";

function money(amount: number, currency: string) {
  return new Intl.NumberFormat(currency === "INR" ? "en-IN" : "en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(amount / 100);
}

function BillingWorkspacePanel({
  api,
  userId,
  identityStatus,
  getToken,
}: {
  api: ReturnType<typeof createApi>;
  userId?: string;
  identityStatus: string;
  getToken: (forceRefresh?: boolean) => Promise<string | null>;
}) {
  const client = useMemo(
    () => createBillingClient(undefined, getToken),
    [getToken],
  );
  const [workspace, setWorkspace] = useState("");
  const [catalog, setCatalog] = useState<CheckoutCatalog | null>(null);
  const [checkout, setCheckout] = useState<CheckoutOutput | null>(null);
  const [provider, setProvider] = useState<BillingProvider>("stripe");
  const [plan, setPlan] = useState<BillingPlan>("starter");
  const [optIn, setOptIn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const generation = useRef(0);
  const requests = useRef<AbortController | null>(null);
  const [, expireLink] = useState(0);
  useEffect(() => {
    if (!checkout || Date.parse(checkout.expires_at) <= Date.now()) return;
    const timer = setTimeout(
      () => expireLink((v) => v + 1),
      Math.min(2147483647, Date.parse(checkout.expires_at) - Date.now() + 1),
    );
    return () => clearTimeout(timer);
  }, [checkout]);

  useEffect(() => {
    const epoch = ++generation.current;
    const controller = new AbortController();
    requests.current = controller;
    setWorkspace("");
    setCatalog(null);
    setCheckout(null);
    setOptIn(false);
    setError("");
    setNotice("");
    if (!userId || identityStatus !== "signed_in") return;
    let active = true;
    void api
      .allowance()
      .then(async (allowance) => {
        if (!active || generation.current !== epoch) return;
        setWorkspace(allowance.workspace_id);
        if (!client.enabled) return;
        const result = await client.catalog(
          allowance.workspace_id,
          controller.signal,
        );
        if (active && generation.current === epoch) {
          setCatalog(result);
          setCheckout(result.current);
        }
      })
      .catch((reason) => {
        if (active && generation.current === epoch)
          setError(
            reason instanceof Error
              ? reason.message
              : "Billing could not be loaded.",
          );
      });
    return () => {
      active = false;
      controller.abort();
      generation.current++;
    };
  }, [api, client, identityStatus, userId]);

  if (!userId || identityStatus !== "signed_in") return null;

  const offer = catalog?.offers.find(
    (item) => item.provider === provider && item.plan === plan,
  );
  const link = checkout ? checkoutLink(checkout) : null;
  const readyForNew = Boolean(
    catalog?.can_start && offer?.configured && !checkout && workspace,
  );

  async function refresh() {
    if (!workspace || busy) return;
    const controller = requests.current;
    const epoch = generation.current;
    if (!controller || controller.signal.aborted) return;
    const current = () =>
      generation.current === epoch && !controller.signal.aborted;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await client.catalog(workspace, controller.signal);
      if (!current()) return;
      setCatalog(result);
      setCheckout(result.current);
      setOptIn(false);
      setNotice("Billing status refreshed from the service.");
    } catch (reason) {
      if (!current()) return;
      setError(
        reason instanceof Error
          ? reason.message
          : "Billing could not be refreshed.",
      );
    } finally {
      if (current()) setBusy(false);
    }
  }

  async function refreshCheckout() {
    if (!workspace || !checkout || busy) return;
    const controller = requests.current;
    const epoch = generation.current;
    if (!controller || controller.signal.aborted) return;
    const current = () =>
      generation.current === epoch && !controller.signal.aborted;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await client.status(
        workspace,
        checkout.id,
        controller.signal,
      );
      if (!current()) return;
      setCheckout(result);
      setNotice(
        "Checkout status refreshed. Access is confirmed separately by the workspace allowance.",
      );
    } catch (reason) {
      if (!current()) return;
      setError(
        reason instanceof Error
          ? reason.message
          : "Checkout status could not be refreshed.",
      );
    } finally {
      if (current()) setBusy(false);
    }
  }

  async function start() {
    if (!workspace || !readyForNew || !optIn || busy) return;
    const controller = requests.current;
    const epoch = generation.current;
    if (!controller || controller.signal.aborted) return;
    const current = () =>
      generation.current === epoch && !controller.signal.aborted;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      let result = await client.start(
        workspace,
        provider,
        plan,
        checkoutIdempotencyKey(workspace, provider, plan),
        controller.signal,
      );
      for (
        let attempt = 0;
        result.state === "dispatching" && attempt < 3;
        attempt++
      ) {
        await new Promise((resolve) => setTimeout(resolve, 750));
        if (!current()) return;
        try {
          result = await client.status(workspace, result.id, controller.signal);
        } catch {
          break;
        }
      }
      if (!current()) return;
      setCheckout(result);
      setCatalog(
        (current) =>
          current && { ...current, can_start: false, current: result },
      );
      setOptIn(false);
      setNotice(
        result.state === "ready"
          ? "Checkout is ready. Review the provider’s final terms before paying."
          : result.state === "dispatching"
            ? "The checkout request is still being verified. Refresh its status before taking another action."
            : "The checkout needs review. Refresh its status before taking another action.",
      );
    } catch (reason) {
      if (!current()) return;
      setError(
        reason instanceof BillingApiError
          ? reason.message
          : "Checkout could not be started. Refresh status before trying again.",
      );
      try {
        const latest = await client.catalog(workspace, controller.signal);
        if (!current()) return;
        setCatalog(latest);
        setCheckout(latest.current);
      } catch {
        // Keep the original error. A safe retry is always a status refresh.
      }
    } finally {
      if (current()) setBusy(false);
    }
  }

  return (
    <details className="workspace-allowance billing-panel">
      <summary>Plans and billing</summary>
      <p>
        Compare the pilot limits for this workspace. Billing starts only after
        you choose a configured plan and confirm that you want to continue to
        its payment provider.
      </p>
      {!client.enabled ? (
        <p role="status">
          Billing checkout is not configured in this build. The research service
          continues to report workspace access and usage.
        </p>
      ) : (
        <>
          {error && (
            <p className="billing-error" role="alert">
              {error}
            </p>
          )}
          {notice && (
            <p className="candidate-meta" role="status">
              {notice}
            </p>
          )}
          {!workspace && !error && (
            <p role="status">Loading workspace billing…</p>
          )}
          {catalog && (
            <>
              <div className="billing-table-wrap">
                <table className="billing-table">
                  <caption>Monthly pilot plans</caption>
                  <thead>
                    <tr>
                      <th scope="col">Provider and plan</th>
                      <th scope="col">Price</th>
                      <th scope="col">Monthly runs</th>
                      <th scope="col">Results per run</th>
                      <th scope="col">Sources per run</th>
                      <th scope="col">Term</th>
                    </tr>
                  </thead>
                  <tbody>
                    {catalog.offers.map((item) => (
                      <tr key={`${item.provider}-${item.plan}`}>
                        <th scope="row">
                          {item.provider === "stripe" ? "Stripe" : "Razorpay"} ·{" "}
                          {item.plan === "starter" ? "Starter" : "Pro"}
                        </th>
                        <td>{money(item.amount_minor, item.currency)}/month</td>
                        <td>{item.runs_per_month}</td>
                        <td>{item.results_per_run}</td>
                        <td>{item.sources_per_run}</td>
                        <td>
                          {item.maximum_monthly_cycles
                            ? `${item.maximum_monthly_cycles} cycles`
                            : "Until canceled"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!catalog.can_start && !checkout && (
                <p className="candidate-meta">
                  Checkout is unavailable until the operator configures and
                  verifies a payment plan.
                </p>
              )}
              {catalog.can_start && !checkout && (
                <fieldset className="billing-choice" disabled={busy}>
                  <legend>Choose a plan</legend>
                  <label>
                    Payment provider
                    <select
                      value={provider}
                      onChange={(event) => {
                        setProvider(event.target.value as BillingProvider);
                        setOptIn(false);
                      }}
                    >
                      <option value="stripe">Stripe · USD</option>
                      <option value="razorpay">Razorpay · INR</option>
                    </select>
                  </label>
                  <label>
                    Plan
                    <select
                      value={plan}
                      onChange={(event) => {
                        setPlan(event.target.value as BillingPlan);
                        setOptIn(false);
                      }}
                    >
                      <option value="starter">Starter</option>
                      <option value="pro">Pro</option>
                    </select>
                  </label>
                  {!offer?.configured && (
                    <p className="candidate-meta">
                      This plan is not available yet. The operator must verify
                      its provider plan before checkout can begin.
                    </p>
                  )}
                  {offer?.configured && (
                    <>
                      <label className="billing-opt-in">
                        <input
                          type="checkbox"
                          checked={optIn}
                          onChange={(event) => setOptIn(event.target.checked)}
                        />
                        I want to continue to{" "}
                        {provider === "stripe" ? "Stripe" : "Razorpay"} for the{" "}
                        {plan} plan at{" "}
                        {money(offer.amount_minor, offer.currency)} per month.
                      </label>
                      <button
                        className="secondary-button"
                        type="button"
                        disabled={!optIn || busy}
                        onClick={() => void start()}
                      >
                        {busy ? "Preparing checkout…" : "Continue to checkout"}
                      </button>
                    </>
                  )}
                </fieldset>
              )}
              {checkout && (
                <div className="billing-current" aria-live="polite">
                  <h3>Current checkout</h3>
                  <p>
                    {checkout.provider === "stripe" ? "Stripe" : "Razorpay"} ·{" "}
                    {checkout.plan === "starter" ? "Starter" : "Pro"} ·{" "}
                    {checkout.state}
                    {checkout.maximum_monthly_cycles
                      ? ` · up to ${checkout.maximum_monthly_cycles} monthly cycles`
                      : " · monthly until canceled"}
                  </p>
                  {checkout.state === "dispatching" && (
                    <p>
                      The provider request is still being confirmed. Refresh
                      status before continuing.
                    </p>
                  )}
                  {checkout.state === "uncertain" && (
                    <p>
                      The provider response needs operator review. Do not start
                      another checkout.
                    </p>
                  )}
                  {checkout.state === "bound" && (
                    <p>
                      The provider subscription is linked. Workspace access is
                      shown in the allowance above and changes only after
                      provider verification.
                    </p>
                  )}
                  {link ? (
                    <a
                      className="secondary-button billing-link"
                      href={link}
                      onClick={(event) => {
                        if (!checkoutLink(checkout)) {
                          event.preventDefault();
                          expireLink((v) => v + 1);
                        }
                      }}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      Review payment with{" "}
                      {checkout.provider === "stripe" ? "Stripe" : "Razorpay"}
                    </a>
                  ) : checkout.state === "ready" ? (
                    <p>
                      The checkout link expired or failed validation. Refresh to
                      check its current status.
                    </p>
                  ) : null}
                  <button
                    className="text-button"
                    type="button"
                    disabled={busy}
                    onClick={() => void refreshCheckout()}
                  >
                    {busy ? "Refreshing…" : "Refresh checkout status"}
                  </button>
                </div>
              )}
              <button
                className="text-button"
                type="button"
                disabled={busy}
                onClick={() => void refresh()}
              >
                Refresh offers and billing status
              </button>
            </>
          )}
        </>
      )}
    </details>
  );
}

export function BillingPanel(
  props: Parameters<typeof BillingWorkspacePanel>[0],
) {
  return (
    <BillingWorkspacePanel
      key={`${props.userId || ""}:${props.identityStatus}`}
      {...props}
    />
  );
}
