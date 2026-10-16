from skriller.billing.plans import PLANS, allowance_for, razorpay_plan_payload, stripe_price_payload


def test_user_approved_monthly_prices_and_caps():
    assert [(p.runs, p.results, p.sources) for p in PLANS.values()] == [(50, 25, 3), (200, 100, 5)]
    for slug, usd, inr in [("starter", 2900, 249900), ("pro", 7900, 649900)]:
        stripe, razorpay = stripe_price_payload(slug), razorpay_plan_payload(slug)
        assert stripe["unit_amount"] == usd and stripe["currency"] == "usd"
        assert stripe["recurring"] == {"interval": "month", "interval_count": 1}
        assert razorpay["item"]["amount"] == inr and razorpay["item"]["currency"] == "INR"
        assert razorpay["period"] == "monthly" and razorpay["interval"] == 1
        allowance = allowance_for(slug, "price_fixture", "cus_fixture")
        assert allowance.monthly is True and allowance.runs == PLANS[slug].runs
