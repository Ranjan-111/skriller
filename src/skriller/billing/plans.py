"""User-approved monthly checkout catalog, monetary values in minor units."""

from dataclasses import dataclass

from skriller.billing.reconcile import Allowance


@dataclass(frozen=True)
class Plan:
    slug: str
    name: str
    runs: int
    results: int
    sources: int
    usd_cents: int
    inr_paise: int


PLANS = {
    "starter": Plan("starter", "Skriller Starter", 50, 25, 3, 2900, 249900),
    "pro": Plan("pro", "Skriller Pro", 200, 100, 5, 7900, 649900),
}


def allowance_for(slug, remote_plan_id, customer_id):
    plan = PLANS[slug]
    return Allowance(
        remote_plan_id, customer_id, plan.runs, plan.results, plan.sources, monthly=True
    )


def stripe_price_payload(slug):
    plan = PLANS[slug]
    return {
        "currency": "usd",
        "unit_amount": plan.usd_cents,
        "recurring": {"interval": "month", "interval_count": 1},
        "product_data": {"name": plan.name},
        "metadata": {"skriller_plan": plan.slug, "catalog_version": "2026-10-17"},
    }


def razorpay_plan_payload(slug):
    plan = PLANS[slug]
    return {
        "period": "monthly",
        "interval": 1,
        "item": {"name": plan.name, "amount": plan.inr_paise, "currency": "INR"},
        "notes": {"skriller_plan": plan.slug, "catalog_version": "2026-10-17"},
    }
