"""Atomic, network-free qualification after the last durable source checkpoint."""

import json

import sqlalchemy as sa

from skriller.db import JobRepository, ResearchRepository
from skriller.db.repositories import insert_row, scope
from skriller.db.schema import attempts, stage_checkpoints
from skriller.erasure import privacy_lock
from skriller.jobs.control import permit_call, plan_for_job
from skriller.qualification.identity import propose_candidates
from skriller.qualification.service import qualify_entity


class _QualificationDeadline(Exception):
    pass


def checkpoint_qualification(session, job, rows):
    """Caller owns the job lock; all local results/finish commit together.

    There is no model call, retry, identity inference or acceptance promotion.
    Checkpoints contain IDs only; current API fits are recomputed from current facts.
    """
    if permit_call(session, job["id"]) <= 0:
        return None
    try:
        with session.begin_nested():
            return _checkpoint(session, job, rows)
    except _QualificationDeadline:
        # Roll back derived rows, then persist the pause outside the savepoint.
        permit_call(session, job["id"])
        return None


def _checkpoint(session, job, rows):
    privacy_lock(session)
    plan = plan_for_job(session, job)
    if len(rows) > 100:
        raise ValueError("Qualification candidates exceed the pilot limit")
    attempt = JobRepository.attempt(
        session, job["id"], f"qualifying:{job['plan_id']}", "qualifying"
    )
    if attempt["state"] == "succeeded":
        return job
    if attempt["state"] != "pending":
        raise ValueError("Qualification checkpoint is not pending")
    identity_summary = propose_candidates(session, [row["id"] for row in rows])
    JobRepository.event(
        session, job["id"], "identity:checkpoint", "identity_suggestions", identity_summary
    )
    identifiers = []
    counts = {"confirmed": 0, "near_match": 0, "excluded": 0}
    outcomes = {"matched": "match", "contradicted": "no_match", "unknown": "unknown"}
    for row in rows:
        entity = ResearchRepository.get_entity(session, row["id"])
        if entity is None or entity["attributes"].get("erased"):
            continue
        fit = qualify_entity(session, plan, row["id"])
        for group in ("essential", "exclusions", "preferences"):
            for index, result in enumerate(getattr(fit, group)):
                ResearchRepository.qualify(
                    session,
                    row["id"],
                    job["plan_id"],
                    json.dumps(
                        {
                            "group": group,
                            "index": index,
                            "criterion": result.criterion.model_dump(mode="json"),
                        },
                        sort_keys=True,
                    ),
                    outcomes[result.outcome],
                    reason=result.reason,
                )
        identifiers.append(row["id"])
        counts[fit.status] += 1
    # Recheck the original deadline after bounded evaluation, before any commit.
    if permit_call(session, job["id"]) <= 0:
        raise _QualificationDeadline()
    now = sa.func.clock_timestamp()
    session.execute(
        sa.update(attempts)
        .where(attempts.c.workspace_id == scope(session), attempts.c.id == attempt["id"])
        .values(
            state="succeeded",
            generation=1,
            started_at=now,
            finished_at=now,
            result_entity_ids=identifiers,
        )
    )
    insert_row(
        session,
        stage_checkpoints,
        job_id=job["id"],
        attempt_id=attempt["id"],
        generation=1,
        stage="qualifying",
        result_refs={"entity_ids": identifiers},
    )
    JobRepository.event(
        session, job["id"], "qualification:completed", "qualification_summary", counts
    )
    return JobRepository.transition(session, job["id"], "running", stage="qualifying")
