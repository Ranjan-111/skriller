from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from test_research_workflow import prepare

from skriller.contracts import Limits, SearchPlan
from skriller.db import ConversationRepository, JobRepository
from skriller.db.schema import jobs
from skriller.jobs.budget import reconcile, reserve

pytestmark = pytest.mark.integration_db


def test_usage_api_splits_confirmed_estimated_and_held_exposure(database, monkeypatch):
    actor = f"usage-{uuid4()}"
    _, client, accepted = prepare(database, monkeypatch, actor)
    with database.tenant(actor, accepted["workspace_id"]) as session:
        job = (
            session.execute(sa.select(jobs).where(jobs.c.id == accepted["job_id"])).mappings().one()
        )
        original = ConversationRepository.get_plan(session, job["plan_id"])
        plan = SearchPlan.model_validate(original["interpretation"]).model_copy(
            update={
                "revision": original["revision"] + 1,
                "limits": Limits(currency_cap=Decimal("1.00")),
            }
        )
        revision = ConversationRepository.revise_plan(
            session,
            job["conversation_id"],
            plan.model_dump(mode="json"),
            parent_id=job["plan_id"],
        )
        session.execute(
            sa.update(jobs)
            .where(jobs.c.workspace_id == accepted["workspace_id"], jobs.c.id == accepted["job_id"])
            .values(plan_id=revision["id"])
        )
        confirmed = reserve(
            session, accepted["job_id"], "confirmed", Decimal("0.10"), {"search_calls": 1}
        )
        reconcile(
            session,
            accepted["job_id"],
            confirmed["id"],
            status="confirmed",
            cost=Decimal("0.03"),
            actual_dimensions={"search_calls": 1},
        )
        estimated = reserve(
            session,
            accepted["job_id"],
            "estimated",
            Decimal("0.20"),
            {"llm_calls": 1, "tokens": 80},
        )
        reconcile(session, accepted["job_id"], estimated["id"], status="estimated")
        reserve(session, accepted["job_id"], "held", Decimal("0.10"), {"fetch_attempts": 1})
        JobRepository.event(
            session,
            accepted["job_id"],
            "metric:success",
            "stage_observation",
            {
                "stage": "discovering",
                "source": "exa_keyless",
                "outcome": "succeeded",
                "attempt_count": 1,
                "attempt_id": str(uuid4()),
                "queue_wait_seconds": 0.25,
                "accepted_result_count": 2,
                "stage_io_seconds": 1.5,
                "cost_usd": "0.03",
                "cost_status": "confirmed",
            },
        )
        JobRepository.event(
            session,
            accepted["job_id"],
            "metric:failure",
            "stage_observation",
            {
                "stage": "discovering",
                "source": "exa_keyless",
                "outcome": "rate_limited",
                "attempt_count": 1,
                "attempt_id": str(uuid4()),
                "queue_wait_seconds": 0.5,
                "accepted_result_count": 0,
                "stage_io_seconds": 0.5,
                "cost_usd": None,
                "cost_status": "estimated",
                "error": "private HTML and synthetic-secret must never be shown",
            },
        )
        JobRepository.event(
            session,
            accepted["job_id"],
            "metric:invalid",
            "stage_observation",
            {
                "stage": "bad value",
                "source": "exa_keyless",
                "outcome": "succeeded",
                "attempt_count": 1,
                "accepted_result_count": 1,
                "stage_io_seconds": 0.5,
                "cost_usd": "0",
                "cost_status": "confirmed",
            },
        )

    response = client.get(
        f"/v1/jobs/{accepted['job_id']}/usage?workspace_id={accepted['workspace_id']}"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["confirmed_cost_usd"] == "0.03"
    assert data["estimated_cost_usd"] == "0.2"
    assert data["reserved_cost_usd"] == "0.1"
    assert data["exposure_ceiling_usd"] == "0.33"
    assert data["remaining_budget_usd"] == "0.67"
    assert data["dimensions"]["confirmed"]["search_calls"] == 1
    assert data["dimensions"]["estimated"]["tokens"] == 80
    assert data["dimensions"]["reserved"]["fetch_attempts"] == 1
    metric = data["stage_metrics"][0]
    assert metric["observations"] == 2 and metric["succeeded"] == 1 and metric["failed"] == 1
    assert metric["accepted_result_count"] == 2 and metric["stage_io_seconds"] == "2"
    assert metric["confirmed_cost_usd"] == "0.03" and metric["unpriced_observations"] == 1
    assert data["invalid_stage_observations"] == 1 and not data["stage_metrics_truncated"]
    assert metric["outcomes"] == {"succeeded": 1, "rate_limited": 1}
    assert metric["correlated_attempt_observations"] == 2
    assert metric["queue_wait_seconds"] == "0.75" and metric["queue_wait_samples"] == 2
    assert "synthetic-secret" not in response.text and "private HTML" not in response.text

    with database.tenant(actor, accepted["workspace_id"]) as session:
        JobRepository.event(
            session,
            accepted["job_id"],
            "collection:measured",
            "collection_summary",
            {
                "source": "web",
                "status": "read",
                "network_seconds": 0.25,
                "parser_seconds": 0.0,
                "browser_seconds": None,
            },
        )
        JobRepository.event(
            session,
            accepted["job_id"],
            "stage:web-success",
            "stage_observation",
            {
                "stage": "collecting",
                "source": "web",
                "outcome": "succeeded",
                "attempt_count": 1,
                "attempt_id": str(uuid4()),
                "queue_wait_seconds": 0,
                "accepted_result_count": 1,
                "stage_io_seconds": 0.25,
                "cost_usd": None,
                "cost_status": "estimated",
            },
        )
    response = client.get(
        f"/v1/jobs/{accepted['job_id']}/usage?workspace_id={accepted['workspace_id']}"
    )
    web_metric = next(
        item for item in response.json()["stage_metrics"]
        if item["stage"] == "collecting" and item["source"] == "web"
    )
    assert web_metric["collection_timings"] == {
        "observations": 1,
        "network_seconds": "0.25",
        "network_samples": 1,
        "parser_seconds": "0",
        "parser_samples": 1,
        "browser_seconds": None,
        "browser_samples": 0,
    }


def test_usage_api_hides_cross_workspace_jobs(database, monkeypatch):
    actor = f"usage-{uuid4()}"
    _, client, accepted = prepare(database, monkeypatch, actor)
    response = client.get(f"/v1/jobs/{accepted['job_id']}/usage?workspace_id={uuid4()}")
    assert response.status_code == 404


def test_stage_metrics_reject_unbounded_or_inconsistent_failure_counts():
    from skriller.research.router import StageMetric

    with pytest.raises(ValueError, match="outcome"):
        StageMetric(
            stage="discovering",
            source="exa_keyless",
            observations=1,
            succeeded=0,
            failed=1,
            accepted_result_count=0,
            stage_io_seconds="1",
            confirmed_cost_usd="0",
            estimated_cost_usd="0",
            unpriced_observations=0,
            outcomes={"made_up_category": 1},
            correlated_attempt_observations=0,
            queue_wait_seconds="0",
            queue_wait_samples=0,
        )
    with pytest.raises(ValueError, match="denominator"):
        StageMetric(
            stage="discovering",
            source="exa_keyless",
            observations=1,
            succeeded=0,
            failed=1,
            accepted_result_count=0,
            stage_io_seconds="1",
            confirmed_cost_usd="0",
            estimated_cost_usd="0",
            unpriced_observations=0,
            outcomes={"source_unavailable": 2},
            correlated_attempt_observations=0,
            queue_wait_seconds="0",
            queue_wait_samples=0,
        )
