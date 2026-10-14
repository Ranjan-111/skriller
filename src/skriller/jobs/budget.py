"""Shared conservative reservations; unconfirmed external work retains its full budget."""

import math
import re
from decimal import Decimal
from typing import TypedDict

import sqlalchemy as sa

from skriller.contracts import SearchPlan
from skriller.db import ConversationRepository, JobRepository
from skriller.db.repositories import money, scope
from skriller.db.schema import jobs, reservations, usage_records

DIMENSIONS = {
    "search_calls": "search_calls",
    "candidates": "candidates",
    "fetch_attempts": "fetch_attempts",
    "llm_calls": "llm_calls",
    "tokens": "token_cap",
}


class StageTotals(TypedDict):
    stage: str
    source: str
    observations: int
    succeeded: int
    failed: int
    accepted_result_count: int
    stage_io_seconds: Decimal
    confirmed_cost_usd: Decimal
    estimated_cost_usd: Decimal
    unpriced_observations: int


class BudgetExhausted(ValueError):
    pass


def dimensions(value):
    if not isinstance(value, dict) or not value:
        raise ValueError("Nonempty bounded reservation dimensions required")
    if any(
        key not in DIMENSIONS
        or isinstance(amount, bool)
        or not isinstance(amount, int)
        or amount < 0
        for key, amount in value.items()
    ):
        raise ValueError("Invalid reservation dimensions")
    return dict(value)


def locked_job(session, job_id):
    row = (
        session.execute(
            sa.select(jobs)
            .where(jobs.c.workspace_id == scope(session), jobs.c.id == job_id)
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise LookupError("Job unavailable")
    return row


def current_usage(session, job_id):
    rows = (
        session.execute(
            sa.select(reservations).where(
                reservations.c.workspace_id == scope(session), reservations.c.job_id == job_id
            )
        )
        .mappings()
        .all()
    )
    total = Decimal(0)
    counters = dict.fromkeys(DIMENSIONS, 0)
    for row in rows:
        if row["state"] == "released":
            continue
        committed = row["state"] == "committed"
        total += row["actual_cost_usd"] if committed else row["amount_usd"]
        used = row["actual_dimensions"] if committed else row["dimensions"]
        for key, count in used.items():
            counters[key] += count
    legacy = (
        session.execute(
            sa.select(usage_records).where(
                usage_records.c.workspace_id == scope(session),
                usage_records.c.job_id == job_id,
                usage_records.c.kind != "budget_reservation",
            )
        )
        .mappings()
        .all()
    )
    for row in legacy:
        total += row["cost_usd"]
        if row["kind"] in counters:
            counters[row["kind"]] += row["quantity"]
    return total, counters


def usage_report(session, job_id):
    """Split confirmed, uncertain and held exposure without treating holds as spend."""
    rows = (
        session.execute(
            sa.select(reservations).where(
                reservations.c.workspace_id == scope(session),
                reservations.c.job_id == job_id,
            )
        )
        .mappings()
        .all()
    )
    amounts = {"confirmed": Decimal(0), "estimated": Decimal(0), "reserved": Decimal(0)}
    counters = {bucket: dict.fromkeys(DIMENSIONS, 0) for bucket in amounts}
    for row in rows:
        if row["state"] == "released":
            continue
        if row["state"] == "held":
            bucket, amount, used = "reserved", row["amount_usd"], row["dimensions"]
        elif row["reconciliation_status"] == "confirmed":
            bucket, amount, used = "confirmed", row["actual_cost_usd"], row["actual_dimensions"]
        elif row["reconciliation_status"] == "estimated":
            bucket, amount, used = "estimated", row["amount_usd"], row["dimensions"]
        else:
            continue
        amounts[bucket] += amount or Decimal(0)
        for key, count in (used or {}).items():
            if key in counters[bucket]:
                counters[bucket][key] += int(count)

    legacy = (
        session.execute(
            sa.select(usage_records).where(
                usage_records.c.workspace_id == scope(session),
                usage_records.c.job_id == job_id,
                usage_records.c.kind != "budget_reservation",
            )
        )
        .mappings()
        .all()
    )
    for row in legacy:
        amounts["confirmed"] += row["cost_usd"]
        if row["kind"] in counters["confirmed"]:
            counters["confirmed"][row["kind"]] += int(row["quantity"])
    return amounts, counters


def stage_observation_report(session, job_id, *, max_events: int = 2000):
    """Aggregate only bounded worker-authored observations for one tenant job."""
    from skriller.db import JobRepository

    totals: dict[tuple[str, str], StageTotals] = {}
    cursor = 0
    read = 0
    invalid = 0
    truncated = False
    while True:
        rows = JobRepository.events_after(session, job_id, cursor, limit=100)
        if not rows:
            break
        for row in rows:
            cursor = row["sequence"]
            read += 1
            if row["kind"] != "stage_observation":
                continue
            data = row["details"]
            try:
                stage, source, outcome = data["stage"], data["source"], data["outcome"]
                if (
                    not isinstance(stage, str)
                    or not re.fullmatch(r"[a-z][a-z0-9_]{0,49}", stage)
                    or not isinstance(source, str)
                    or not re.fullmatch(r"[a-z][a-z0-9_.:-]{0,99}", source)
                    or outcome not in {"succeeded", "source_unavailable"}
                    or data["attempt_count"] != 1
                    or isinstance(data["accepted_result_count"], bool)
                    or not isinstance(data["accepted_result_count"], int)
                    or not 0 <= data["accepted_result_count"] <= 300
                    or isinstance(data["stage_io_seconds"], bool)
                    or not isinstance(data["stage_io_seconds"], (int, float))
                    or not math.isfinite(data["stage_io_seconds"])
                    or not 0 <= data["stage_io_seconds"] <= 180
                    or data["cost_status"] not in {"confirmed", "estimated"}
                ):
                    raise ValueError
                amount = data.get("cost_usd")
                cost = Decimal(str(amount)) if amount is not None else Decimal(0)
                if not cost.is_finite() or cost < 0:
                    raise ValueError
            except (KeyError, TypeError, ValueError, ArithmeticError):
                invalid += 1
                continue
            key = (stage, source)
            summary = totals.setdefault(
                key,
                {
                    "stage": stage,
                    "source": source,
                    "observations": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "accepted_result_count": 0,
                    "stage_io_seconds": Decimal(0),
                    "confirmed_cost_usd": Decimal(0),
                    "estimated_cost_usd": Decimal(0),
                    "unpriced_observations": 0,
                },
            )
            summary["observations"] += 1
            summary["succeeded"] += outcome == "succeeded"
            summary["failed"] += outcome != "succeeded"
            summary["accepted_result_count"] += data["accepted_result_count"]
            summary["stage_io_seconds"] += Decimal(str(data["stage_io_seconds"]))
            if amount is None:
                summary["unpriced_observations"] += 1
            elif data["cost_status"] == "confirmed":
                summary["confirmed_cost_usd"] += cost
            else:
                summary["estimated_cost_usd"] += cost
        if len(rows) < 100:
            break
        if read >= max_events:
            truncated = True
            break
    return [totals[key] for key in sorted(totals)], invalid, truncated


def reserve(session, job_id, key, maximum_cost, requested_dimensions):
    request = dimensions(requested_dimensions)
    maximum = money(maximum_cost)
    job = locked_job(session, job_id)
    existing = (
        session.execute(
            sa.select(reservations).where(
                reservations.c.workspace_id == scope(session),
                reservations.c.job_id == job_id,
                reservations.c.idempotency_key == key,
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing:
        if (
            existing["job_id"] != job_id
            or existing["amount_usd"] != maximum
            or existing["dimensions"] != request
        ):
            raise ValueError("Reservation key reused for a different operation")
        return dict(existing)
    if job["state"] not in {"queued", "running"}:
        raise ValueError("Job does not permit new calls")
    persisted = ConversationRepository.get_plan(session, job["plan_id"])
    plan = SearchPlan.model_validate(persisted["interpretation"])
    if (
        str(plan.workspace_id) != scope(session)
        or str(plan.conversation_id) != job["conversation_id"]
        or plan.revision != persisted["revision"]
    ):
        raise ValueError("Plan does not match job scope")
    total, counters = current_usage(session, job_id)
    if total + maximum > plan.limits.currency_cap or any(
        counters[name] + request.get(name, 0) > getattr(plan.limits, cap)
        for name, cap in DIMENSIONS.items()
    ):
        raise BudgetExhausted("Job budget exhausted")
    record = JobRepository.reserve(session, job_id, key, maximum)
    session.execute(
        sa.update(reservations)
        .where(reservations.c.id == record["id"], reservations.c.workspace_id == scope(session))
        .values(dimensions=request)
    )
    return {**record, "dimensions": request}


def reconcile(session, job_id, reservation_id, *, status, cost=None, actual_dimensions=None):
    job = locked_job(session, job_id)
    row = (
        session.execute(
            sa.select(reservations).where(
                reservations.c.workspace_id == scope(session),
                reservations.c.job_id == job_id,
                reservations.c.id == reservation_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise LookupError("Reservation unavailable")
    if status not in {"estimated", "confirmed", "not_charged"}:
        raise ValueError("Explicit charge outcome required")
    if status == "estimated":
        amount, actual = row["amount_usd"], row["dimensions"]
    elif status == "not_charged":
        if cost not in (None, 0) or actual_dimensions not in (None, {}):
            raise ValueError("Not-charged outcome must be zero")
        amount, actual = Decimal(0), {}
    else:
        if cost is None or actual_dimensions is None:
            raise ValueError("Confirmed usage requires actual cost and dimensions")
        amount, actual = money(cost), dimensions(actual_dimensions)
    if row["reconciliation_status"] == status:
        if row["actual_cost_usd"] != amount or row["actual_dimensions"] != actual:
            raise ValueError("Conflicting idempotent reconciliation")
        return dict(row)
    if row["state"] != "held" and row["reconciliation_status"] != "estimated":
        raise ValueError("Final reconciliation is immutable")
    overrun = amount > row["amount_usd"] or any(
        actual.get(key, 0) > row["dimensions"].get(key, 0) for key in actual
    )
    state = "released" if status == "not_charged" else "committed"
    result = dict(
        session.execute(
            sa.update(reservations)
            .where(
                reservations.c.workspace_id == scope(session), reservations.c.id == reservation_id
            )
            .values(
                state=state,
                reconciliation_status=status,
                actual_cost_usd=amount,
                actual_dimensions=actual,
            )
            .returning(reservations)
        )
        .mappings()
        .one()
    )
    if row["state"] == "held":
        JobRepository.usage(
            session, job_id, f"reservation:{reservation_id}", "budget_reservation", 0, amount
        )
    # Outcome revisions append audit events; current totals use each reservation once.
    JobRepository.event(
        session,
        job_id,
        f"budget:{reservation_id}:{status}",
        "usage_reconciled",
        {
            "reservation_id": str(reservation_id),
            "status": status,
            "cost_usd": str(amount),
            "dimensions": actual,
            "overrun": overrun,
        },
    )
    if overrun and job["state"] in {"queued", "running"}:
        JobRepository.transition(session, job_id, "paused")
    return result
