"""Repositories require a verified tenant session; database policies are independent."""

import sqlalchemy as sa

from .core import WorkspaceAccessDenied
from .schema import memberships, workspaces


def scope(session):
    workspace = session.info.get("workspace_id")
    if not workspace:
        raise WorkspaceAccessDenied("Tenant session required")
    return workspace


def require_owner(session):
    workspace = scope(session)
    role = session.execute(
        sa.select(memberships.c.role).where(
            memberships.c.workspace_id == workspace,
            memberships.c.actor_id == session.info["actor_id"],
        )
    ).scalar_one_or_none()
    if role != "owner":
        raise WorkspaceAccessDenied("Workspace owner permission required")


class WorkspaceRepository:
    @staticmethod
    def get(session):
        return (
            session.execute(sa.select(workspaces).where(workspaces.c.id == scope(session)))
            .mappings()
            .one()
        )

    @staticmethod
    def add_member(session, actor_id: str, role: str = "member"):
        require_owner(session)
        if not actor_id or len(actor_id) > 128 or role not in {"owner", "member"}:
            raise ValueError("Valid member identity and role required")
        session.execute(
            sa.insert(memberships).values(workspace_id=scope(session), actor_id=actor_id, role=role)
        )


def insert_row(session, table, **values):
    return dict(
        session.execute(
            sa.insert(table).values(workspace_id=scope(session), **values).returning(table)
        )
        .mappings()
        .one()
    )


class ConversationRepository:
    @staticmethod
    def create(session, title: str):
        from .schema import conversations

        return insert_row(session, conversations, title=title, created_by=session.info["actor_id"])

    @staticmethod
    def get(session, conversation_id: str):
        from .schema import conversations

        return (
            session.execute(
                sa.select(conversations).where(
                    conversations.c.workspace_id == scope(session),
                    conversations.c.id == conversation_id,
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def add_message(session, conversation_id: str, role: str, content: str):
        from .schema import conversations, messages

        parent = session.execute(
            sa.select(conversations.c.id)
            .where(
                conversations.c.workspace_id == scope(session),
                conversations.c.id == conversation_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if parent is None:
            raise LookupError("Conversation unavailable")
        sequence = (
            session.execute(
                sa.select(sa.func.coalesce(sa.func.max(messages.c.sequence), 0)).where(
                    messages.c.workspace_id == scope(session),
                    messages.c.conversation_id == conversation_id,
                )
            ).scalar_one()
            + 1
        )
        return insert_row(
            session,
            messages,
            conversation_id=conversation_id,
            role=role,
            content=content,
            sequence=sequence,
        )

    @staticmethod
    def revise_plan(
        session, conversation_id: str, interpretation: dict, parent_id: str | None = None
    ):
        from .schema import conversations, plans

        parent = session.execute(
            sa.select(conversations.c.id)
            .where(
                conversations.c.workspace_id == scope(session),
                conversations.c.id == conversation_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if parent is None:
            raise LookupError("Conversation unavailable")
        previous = (
            session.execute(
                sa.select(plans)
                .where(
                    plans.c.workspace_id == scope(session),
                    plans.c.conversation_id == conversation_id,
                )
                .order_by(plans.c.revision.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        expected_parent = previous["id"] if previous else None
        if parent_id != expected_parent:
            raise ValueError("Refinement must reference the latest immutable plan")
        revision = previous["revision"] + 1 if previous else 1
        return insert_row(
            session,
            plans,
            conversation_id=conversation_id,
            parent_id=parent_id,
            revision=revision,
            interpretation=interpretation,
            created_by=session.info["actor_id"],
        )

    @staticmethod
    def get_plan(session, plan_id: str):
        from .schema import plans

        return (
            session.execute(
                sa.select(plans).where(
                    plans.c.workspace_id == scope(session), plans.c.id == plan_id
                )
            )
            .mappings()
            .one_or_none()
        )


class ResearchRepository:
    @staticmethod
    def get_entity(session, entity_id: str):
        from .schema import entities

        return (
            session.execute(
                sa.select(entities).where(
                    entities.c.workspace_id == scope(session), entities.c.id == entity_id
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def get_evidence(session, evidence_id: str):
        from .schema import evidence

        return (
            session.execute(
                sa.select(evidence).where(
                    evidence.c.workspace_id == scope(session), evidence.c.id == evidence_id
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def entity(
        session,
        kind: str,
        display_name: str | None = None,
        canonical_key: str | None = None,
        attributes: dict | None = None,
    ):
        from .schema import entities

        return insert_row(
            session,
            entities,
            kind=kind,
            display_name=display_name,
            canonical_key=canonical_key,
            attributes=attributes or {},
        )

    @staticmethod
    def add_evidence(
        session,
        *,
        source_url: str,
        source_platform: str,
        collected_at,
        excerpt: str | None = None,
        object_key: str | None = None,
        content_hash: str | None = None,
        expires_at=None,
    ):
        from .schema import evidence

        return insert_row(
            session,
            evidence,
            source_url=source_url,
            source_platform=source_platform,
            collected_at=collected_at,
            excerpt=excerpt,
            object_key=object_key,
            content_hash=content_hash,
            expires_at=expires_at,
        )

    @staticmethod
    def claim(
        session,
        entity_id: str,
        field: str,
        value,
        *,
        mode: str,
        evidence_ids: list[str],
        status: str = "unverified",
        confidence=None,
    ):
        from .schema import claim_evidence, claims

        if mode in {"observed", "inferred"} and not evidence_ids:
            raise ValueError("Observed/inferred claims require evidence")
        if mode == "unavailable" and value is not None:
            raise ValueError("Unavailable claims must preserve null values")
        from .schema import entities

        entity = session.execute(
            sa.select(entities.c.id)
            .where(entities.c.workspace_id == scope(session), entities.c.id == entity_id)
            .with_for_update()
        ).scalar_one_or_none()
        if entity is None:
            raise LookupError("Entity unavailable")
        prior = (
            session.execute(
                sa.select(claims).where(
                    claims.c.workspace_id == scope(session),
                    claims.c.entity_id == entity_id,
                    claims.c.field == field,
                )
            )
            .mappings()
            .all()
        )
        contradictions = [
            item["id"]
            for item in prior
            if value is not None and item["value"] is not None and item["value"] != value
        ]
        if contradictions:
            status = "conflict"
            session.execute(
                sa.update(claims)
                .where(claims.c.workspace_id == scope(session), claims.c.id.in_(contradictions))
                .values(status="conflict")
            )
        claim = insert_row(
            session,
            claims,
            entity_id=entity_id,
            field=field,
            value=value,
            mode=mode,
            status=status,
            confidence=confidence,
        )
        for evidence_id in set(evidence_ids):
            session.execute(
                sa.insert(claim_evidence).values(
                    workspace_id=scope(session), claim_id=claim["id"], evidence_id=evidence_id
                )
            )
        return claim

    @staticmethod
    def claims_for(session, entity_id: str):
        from .schema import claims

        return (
            session.execute(
                sa.select(claims)
                .where(claims.c.workspace_id == scope(session), claims.c.entity_id == entity_id)
                .order_by(claims.c.created_at, claims.c.id)
            )
            .mappings()
            .all()
        )

    @staticmethod
    def link(session, source_id: str, target_id: str, relation: str):
        from .schema import entity_links

        return insert_row(
            session, entity_links, source_id=source_id, target_id=target_id, relation=relation
        )

    @staticmethod
    def qualify(
        session,
        entity_id: str,
        plan_id: str,
        criterion: str,
        outcome: str,
        reason: str | None = None,
        claim_id: str | None = None,
    ):
        from .schema import qualifications

        return insert_row(
            session,
            qualifications,
            entity_id=entity_id,
            plan_id=plan_id,
            criterion=criterion,
            outcome=outcome,
            reason=reason,
            claim_id=claim_id,
        )

    @staticmethod
    def suppress(session, kind: str, key: str, reason: str):
        from .schema import suppressions

        return insert_row(
            session,
            suppressions,
            kind=kind,
            key=key,
            reason=reason,
            created_by=session.info["actor_id"],
        )

    @staticmethod
    def is_suppressed(session, kind: str, key: str):
        from .schema import suppressions

        return (
            session.execute(
                sa.select(suppressions.c.id).where(
                    suppressions.c.workspace_id == scope(session),
                    suppressions.c.kind == kind,
                    suppressions.c.key == key,
                )
            ).first()
            is not None
        )


def insert_once(session, table, values: dict, key_names: list[str], *, immutable_keys=None):
    """Atomic deduplication; a key cannot silently name a different logical operation."""
    from sqlalchemy.dialects.postgresql import insert

    values = {"workspace_id": scope(session), **values}
    row = (
        session.execute(
            insert(table)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["workspace_id", *key_names])
            .returning(table)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        condition = [table.c[name] == values[name] for name in ["workspace_id", *key_names]]
        row = session.execute(sa.select(table).where(*condition)).mappings().one()
        for name in immutable_keys or values:
            if row[name] != values[name]:
                raise ValueError("Idempotency key reused with different operation")
    return dict(row)


class JobRepository:
    @staticmethod
    def create(session, conversation_id: str, plan_id: str, idempotency_key: str):
        from .schema import jobs

        return insert_once(
            session,
            jobs,
            {
                "conversation_id": conversation_id,
                "plan_id": plan_id,
                "idempotency_key": idempotency_key,
                "created_by": session.info["actor_id"],
                "state": "planned",
                "version": 1,
            },
            ["idempotency_key"],
            immutable_keys=["conversation_id", "plan_id", "created_by"],
        )

    @staticmethod
    def get(session, job_id: str):
        from .schema import jobs

        return (
            session.execute(
                sa.select(jobs).where(jobs.c.workspace_id == scope(session), jobs.c.id == job_id)
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def transition(
        session,
        job_id: str,
        state: str,
        *,
        expected_state: str | None = None,
        expected_version: int | None = None,
        stage: str | None = None,
        failure_code: str | None = None,
        terminal_reason: str | None = None,
    ):
        from skriller.jobs.state import TERMINAL_STATES, validate_transition

        from .schema import jobs

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
        if expected_state is not None and row["state"] != expected_state:
            raise ValueError("Job state changed concurrently")
        if expected_version is not None and row["version"] != expected_version:
            raise ValueError("Job version changed concurrently")
        next_stage = stage if stage is not None else row["stage"]
        requested_reason = terminal_reason
        if state == row["state"] and state in TERMINAL_STATES and requested_reason is None:
            requested_reason = row["terminal_reason"]
        reason = validate_transition(row["state"], state, next_stage, requested_reason)
        if state == row["state"] and row["state"] in TERMINAL_STATES:
            if (
                next_stage != row["stage"]
                or reason != row["terminal_reason"]
                or (failure_code is not None and failure_code != row["failure_code"])
            ):
                raise ValueError("Terminal job outcome cannot change")
            return dict(row)
        if state == row["state"] and next_stage == row["stage"]:
            return dict(row)
        updates = {
            "state": state,
            "version": row["version"] + 1,
            "stage": next_stage,
            "failure_code": failure_code,
            "terminal_reason": reason,
        }
        if state in TERMINAL_STATES:
            updates["completed_at"] = sa.func.now()
        result = dict(
            session.execute(
                sa.update(jobs)
                .where(jobs.c.workspace_id == scope(session), jobs.c.id == job_id)
                .values(**updates)
                .returning(jobs)
            )
            .mappings()
            .one()
        )
        JobRepository.event(
            session,
            job_id,
            f"state:{result['version']}",
            "state_changed",
            {
                "from_state": row["state"],
                "state": state,
                "stage": next_stage,
                "version": result["version"],
                "terminal_reason": reason,
            },
        )
        return result

    @staticmethod
    def attempt(session, job_id: str, logical_key: str, stage: str):
        from .schema import attempts

        return insert_once(
            session,
            attempts,
            {"job_id": job_id, "logical_key": logical_key, "stage": stage, "state": "pending"},
            ["job_id", "logical_key"],
            immutable_keys=["job_id", "logical_key", "stage"],
        )

    @staticmethod
    def event(session, job_id: str, event_key: str, kind: str, details: dict | None = None):
        from .schema import job_events, jobs

        # Allocate sequence IDs only while holding the same per-job lock used
        # by state mutation. A later sequence cannot commit before an earlier
        # event for this job, so resumable cursors cannot skip delayed commits.
        available = session.execute(
            sa.select(jobs.c.id)
            .where(jobs.c.workspace_id == scope(session), jobs.c.id == job_id)
            .with_for_update()
        ).scalar_one_or_none()
        if available is None:
            raise LookupError("Job unavailable")

        return insert_once(
            session,
            job_events,
            {"job_id": job_id, "event_key": event_key, "kind": kind, "details": details or {}},
            ["job_id", "event_key"],
        )

    @staticmethod
    def events_after(session, job_id: str, cursor: int = 0, limit: int = 100):
        from .schema import job_events

        if cursor < 0 or not 1 <= limit <= 1000:
            raise ValueError("Invalid event cursor/limit")
        return (
            session.execute(
                sa.select(job_events)
                .where(
                    job_events.c.workspace_id == scope(session),
                    job_events.c.job_id == job_id,
                    job_events.c.sequence > cursor,
                )
                .order_by(job_events.c.sequence)
                .limit(limit)
            )
            .mappings()
            .all()
        )

    @staticmethod
    def enqueue(
        session,
        job_id: str,
        idempotency_key: str,
        *,
        topic: str = "execute_job",
        attempt_id: str | None = None,
    ):
        from .schema import outbox

        return insert_once(
            session,
            outbox,
            {
                "job_id": job_id,
                "actor_id": session.info["actor_id"],
                "attempt_id": attempt_id,
                "topic": topic,
                "idempotency_key": idempotency_key,
            },
            ["idempotency_key"],
        )

    @staticmethod
    def broker_payload(record) -> dict:
        fields = ["workspace_id", "job_id", "actor_id"]
        if record.get("attempt_id"):
            fields.append("attempt_id")
        return {name: str(record[name]) for name in fields}

    @staticmethod
    def usage(
        session,
        job_id: str,
        idempotency_key: str,
        kind: str,
        quantity,
        cost_usd,
        *,
        attempt_id: str | None = None,
    ):
        from .schema import usage_records

        return insert_once(
            session,
            usage_records,
            {
                "job_id": job_id,
                "idempotency_key": idempotency_key,
                "kind": kind,
                "quantity": money(quantity),
                "cost_usd": money(cost_usd),
                "attempt_id": attempt_id,
            },
            ["idempotency_key"],
        )

    @staticmethod
    def reserve(session, job_id: str, idempotency_key: str, amount_usd):
        from .schema import reservations

        return insert_once(
            session,
            reservations,
            {
                "job_id": job_id,
                "idempotency_key": idempotency_key,
                "amount_usd": money(amount_usd),
                "state": "held",
            },
            ["idempotency_key"],
            immutable_keys=["job_id", "amount_usd"],
        )


JOB_TRANSITIONS = {
    "planned": {"queued", "waiting_for_connection", "cancelled"},
    "queued": {"running", "waiting_for_connection", "paused", "partial", "failed", "cancelled"},
    "running": {"waiting_for_connection", "paused", "completed", "partial", "failed", "cancelled"},
    "waiting_for_connection": {"queued", "running", "paused", "partial", "failed", "cancelled"},
    "paused": {"queued", "running", "waiting_for_connection", "partial", "cancelled", "failed"},
    "completed": set(),
    "partial": set(),
    "failed": set(),
    "cancelled": set(),
}


def money(value):
    from decimal import Decimal

    amount = Decimal(str(value))
    if (
        not amount.is_finite()
        or amount < 0
        or amount > Decimal("999999999999.99999999")
        or amount != amount.quantize(Decimal("0.00000001"))
    ):
        raise ValueError(
            "Usage amounts must be finite, nonnegative and at most eight decimal places"
        )
    return amount
