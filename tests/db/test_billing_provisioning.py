import json
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa

from skriller.billing.provisioning import provision_plan, remote_plans
from skriller.billing.runtime import ProviderConfiguration
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db


@pytest.mark.parametrize("provider", ["stripe", "razorpay"])
def test_creates_user_approved_price_once_and_reuses_durable_receipt(database, provider):
    config = ProviderConfiguration(
        provider,
        ("acct_" if provider == "stripe" else "acc_") + uuid4().hex,
        False,
        b"fixture-webhook-secret",
        ("sk_test_" if provider == "stripe" else "rzp_test_") + "fixture_only",
        api_secret="fixture_secret_only",
        stripe_version="2025-06-30.basil",
    )
    engine = sa.create_engine(Settings().database_url)
    requests = []

    def respond(request):
        requests.append(request)
        assert request.method == "POST"
        if provider == "stripe":
            data = parse_qs(request.content.decode())
            assert data["unit_amount"] == ["2900"] and data["currency"] == ["usd"]
            assert data["recurring[interval]"] == ["month"]
            assert request.headers["Idempotency-Key"].startswith("skriller-plan-")
            return httpx.Response(
                200,
                json={
                    "id": "price_fixture",
                    "object": "price",
                    "currency": "usd",
                    "unit_amount": 2900,
                    "livemode": False,
                    "recurring": {"interval": "month", "interval_count": 1},
                },
            )
        data = json.loads(request.content)
        assert data["item"]["amount"] == 249900 and data["period"] == "monthly"
        return httpx.Response(
            200,
            json={
                "id": "plan_fixture",
                "entity": "plan",
                "period": "monthly",
                "interval": 1,
                "item": {"amount": 249900, "currency": "INR"},
            },
        )

    try:
        for _ in range(2):
            assert provision_plan(
                engine, config, "starter", transport=httpx.MockTransport(respond)
            ) == {
                "state": "ready",
                "remote_id": "price_fixture" if provider == "stripe" else "plan_fixture",
            }
        assert len(requests) == 1
    finally:
        engine.dispose()


def test_unknown_write_outcome_never_blindly_creates_another_plan(database):
    config = ProviderConfiguration(
        "razorpay",
        "acc_" + uuid4().hex,
        False,
        b"fixture-webhook-secret",
        "rzp_test_fixture_only",
        api_secret="fixture_secret_only",
    )
    engine = sa.create_engine(Settings().database_url)
    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("Synthetic response lost after provider creation")

    try:
        for _ in range(2):
            assert provision_plan(
                engine, config, "pro", transport=httpx.MockTransport(timeout)
            ) == {"state": "requires_reconciliation", "remote_id": None}
        assert len(calls) == 1
        with engine.begin() as connection:
            row = (
                connection.execute(
                    sa.select(remote_plans).where(remote_plans.c.account_scope == config.scope)
                )
                .mappings()
                .one()
            )
            assert row["state"] == "uncertain" and row["remote_id"] is None
    finally:
        engine.dispose()
