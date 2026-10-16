"""Published professional contacts and evidence-dated role history, without IO.

Accepted observations come from SKR-047's trusted subject binding. DNS results
may describe a domain, never a mailbox. No SMTP, address guessing, cross-person
company-domain propagation or collection-time role supersession occurs here.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Literal

import sqlalchemy as sa
from agent_reach.utils.url import normalize_public_http_url
from sqlalchemy.dialects.postgresql import UUID

from skriller.db.repositories import ResearchRepository, insert_row, scope
from skriller.db.schema import claim_evidence, claims, evidence, scoped
from skriller.extraction.validation import literal_value

role_history = scoped(
    "role_history",
    sa.Column("previous_id", UUID(as_uuid=False), nullable=False),
    sa.Column("replacement_id", UUID(as_uuid=False), nullable=False),
    sa.Column("previous_date_id", UUID(as_uuid=False), nullable=False),
    sa.Column("replacement_date_id", UUID(as_uuid=False), nullable=False),
    sa.Column("previous_evidence_id", UUID(as_uuid=False), nullable=False),
    sa.Column("replacement_evidence_id", UUID(as_uuid=False), nullable=False),
    sa.Column("effective_date", sa.Date, nullable=False),
    sa.Column("actor_id", sa.String(128), nullable=False),
    sa.Column("review_hash", sa.String(64)),
    constraints=(
        sa.CheckConstraint("previous_id<>replacement_id"),
        sa.UniqueConstraint("workspace_id", "previous_id", "replacement_id"),
        *[
            sa.ForeignKeyConstraint(["workspace_id", name], ["claims.workspace_id", "claims.id"])
            for name in ("previous_id", "replacement_id", "previous_date_id", "replacement_date_id")
        ],
        *[
            sa.ForeignKeyConstraint(
                ["workspace_id", name], ["evidence.workspace_id", "evidence.id"]
            )
            for name in ("previous_evidence_id", "replacement_evidence_id")
        ],
    ),
)


@dataclass(frozen=True)
class ContactCheck:
    email: str | None
    syntax_status: Literal["valid", "invalid"]
    domain_status: Literal["mx_present", "mx_absent", "not_checked", "invalid"]
    ownership_status: Literal["published_professional", "unverified"]
    mailbox_status: Literal["not_checked"] = "not_checked"
    reason: str = ""
    claim_id: str | None = None


def email_domain(value: str) -> str | None:
    """Conservative ASCII mailbox syntax; unsupported syntax is not guessed."""
    if not isinstance(value, str) or len(value) > 254 or value.count("@") != 1:
        return None
    local, domain = value.rsplit("@", 1)
    if not 1 <= len(local) <= 64 or local.startswith(".") or local.endswith(".") or ".." in local:
        return None
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", local):
        return None
    try:
        ascii_domain = domain.encode("idna").decode("ascii").lower()
        normalize_public_http_url("https://" + ascii_domain)
    except (ValueError, UnicodeError):
        return None
    labels = ascii_domain.split(".")
    if len(labels) < 2 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels
    ):
        return None
    if labels[-1].isdigit():
        return None
    return ascii_domain


def _observed(session, claim_id: str, evidence_id: str, *, now: datetime, reviewed=True):
    row = (
        session.execute(
            sa.select(
                claims.c.id,
                claims.c.entity_id,
                claims.c.field,
                claims.c.value,
                evidence.c.id.label("evidence_id"),
                evidence.c.excerpt,
                evidence.c.source_url,
                evidence.c.collected_at,
            )
            .join(
                claim_evidence,
                sa.and_(
                    claims.c.workspace_id == claim_evidence.c.workspace_id,
                    claims.c.id == claim_evidence.c.claim_id,
                ),
            )
            .join(
                evidence,
                sa.and_(
                    evidence.c.workspace_id == claim_evidence.c.workspace_id,
                    evidence.c.id == claim_evidence.c.evidence_id,
                ),
            )
            .where(
                claims.c.workspace_id == scope(session),
                claims.c.id == claim_id,
                evidence.c.id == evidence_id,
                claims.c.status == "accepted"
                if reviewed
                else claims.c.status.in_(["accepted", "conflict", "unverified"]),
                claims.c.mode == "observed",
                sa.or_(evidence.c.expires_at.is_(None), evidence.c.expires_at > now),
            )
        )
        .mappings()
        .one_or_none()
    )
    if (
        row is None
        or not isinstance(row["value"], str)
        or not row["excerpt"]
        or not literal_value(row["value"], row["excerpt"])
    ):
        return None
    return row


def check_contact(
    session,
    entity_id: str,
    value: str,
    *,
    claim_id: str | None = None,
    evidence_id: str | None = None,
    mx_status: Literal["present", "absent", "not_checked"] = "not_checked",
) -> ContactCheck:
    if ResearchRepository.get_entity(session, entity_id) is None:
        raise LookupError("Entity unavailable")
    if mx_status not in {"present", "absent", "not_checked"}:
        raise ValueError("Bounded domain observation required")
    domain = email_domain(value)
    if domain is None:
        return ContactCheck(None, "invalid", "invalid", "unverified", reason="syntax_invalid")
    domain_status: Literal["mx_present", "mx_absent", "not_checked", "invalid"]
    if mx_status == "present":
        domain_status = "mx_present"
    elif mx_status == "absent":
        domain_status = "mx_absent"
    else:
        domain_status = "not_checked"
    row = (
        _observed(session, claim_id, evidence_id, now=datetime.now(UTC))
        if claim_id and evidence_id
        else None
    )
    # Field identity and professional-channel attribution are established by
    # trusted extraction, not guessed from a company's domain or a local part.
    if (
        row is None
        or row["entity_id"] != entity_id
        or row["value"] != value
        or row["field"] not in {"work_email", "professional_email"}
    ):
        return ContactCheck(
            None, "valid", domain_status, "unverified", reason="professional_ownership_unproven"
        )
    try:
        normalize_public_http_url(row["source_url"])
    except ValueError:
        return ContactCheck(
            None, "valid", domain_status, "unverified", reason="publication_source_invalid"
        )
    return ContactCheck(
        value,
        "valid",
        domain_status,
        "published_professional",
        reason="published_observation",
        claim_id=claim_id,
    )


@dataclass(frozen=True)
class DatedRole:
    role_claim_id: str
    date_claim_id: str
    evidence_id: str


def _dated(session, observation: DatedRole, now: datetime, *, reviewed=True):
    role = _observed(
        session, observation.role_claim_id, observation.evidence_id, now=now, reviewed=reviewed
    )
    dating = _observed(
        session, observation.date_claim_id, observation.evidence_id, now=now, reviewed=reviewed
    )
    if (
        role is None
        or dating is None
        or role["entity_id"] != dating["entity_id"]
        or role["field"] not in {"current_role", "job_title"}
        or dating["field"] != "role_effective_date"
    ):
        return None
    try:
        effective = date.fromisoformat(dating["value"])
    except ValueError:
        return None
    if effective > now.date():
        return None
    return role, effective


def record_role_refresh(
    session, previous: DatedRole, replacement: DatedRole, *, review_hash: str | None = None
) -> str:
    """Record only a proven chronological change; retain both original claims."""
    session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": "role-history:" + scope(session)},
    )
    now = datetime.now(UTC)
    if review_hash is not None and not re.fullmatch(r"[0-9a-f]{64}", review_hash):
        raise ValueError("Review hash must identify the reviewed source context")
    old, new = _dated(session, previous, now), _dated(session, replacement, now)
    if old is None or new is None:
        return "unknown_dates_or_evidence"
    if old[0]["entity_id"] != new[0]["entity_id"] or old[0]["field"] != new[0]["field"]:
        return "identity_or_field_mismatch"
    if new[1] <= old[1] or old[0]["value"] == new[0]["value"]:
        return "ambiguous_or_unchanged"
    existing = session.execute(
        sa.select(role_history.c.id).where(
            role_history.c.workspace_id == scope(session),
            role_history.c.previous_id == previous.role_claim_id,
            role_history.c.replacement_id == replacement.role_claim_id,
        )
    ).scalar_one_or_none()
    if existing is None:
        insert_row(
            session,
            role_history,
            previous_id=previous.role_claim_id,
            replacement_id=replacement.role_claim_id,
            previous_date_id=previous.date_claim_id,
            replacement_date_id=replacement.date_claim_id,
            previous_evidence_id=previous.evidence_id,
            replacement_evidence_id=replacement.evidence_id,
            effective_date=new[1],
            actor_id=session.info["actor_id"],
            review_hash=review_hash,
        )
    return "superseded"


def role_projection(session, entity_id: str) -> list[dict]:
    """Original entity only: conflicting or expired refresh remains unknown."""
    if ResearchRepository.get_entity(session, entity_id) is None:
        raise LookupError("Entity unavailable")
    roles = (
        session.execute(
            sa.select(claims)
            .where(
                claims.c.workspace_id == scope(session),
                claims.c.entity_id == entity_id,
                claims.c.field.in_(["current_role", "job_title"]),
            )
            .limit(101)
        )
        .mappings()
        .all()
    )
    if len(roles) > 100:
        raise ValueError("Role projection exceeds claim budget")
    history = (
        session.execute(
            sa.select(role_history)
            .where(
                role_history.c.workspace_id == scope(session),
                role_history.c.previous_id.in_([row["id"] for row in roles]),
            )
            .limit(201)
        )
        .mappings()
        .all()
    )
    if len(history) > 200:
        raise ValueError("Role history exceeds projection budget")
    now = datetime.now(UTC)
    valid = []
    for item in history:
        old = DatedRole(item["previous_id"], item["previous_date_id"], item["previous_evidence_id"])
        new = DatedRole(
            item["replacement_id"], item["replacement_date_id"], item["replacement_evidence_id"]
        )
        old_fact, new_fact = _dated(session, old, now), _dated(session, new, now)
        if (
            old_fact
            and new_fact
            and old_fact[0]["entity_id"] == new_fact[0]["entity_id"]
            and old_fact[0]["field"] == new_fact[0]["field"]
            and new_fact[1] > old_fact[1]
            and new_fact[1] == item["effective_date"]
            and old_fact[0]["value"] != new_fact[0]["value"]
        ):
            valid.append(item)
    superseded = {item["previous_id"] for item in valid}
    active = [
        row
        for row in roles
        if row["id"] not in superseded and row["status"] == "accepted" and row["mode"] == "observed"
    ]
    current_ids = {item["replacement_id"] for item in valid} & {row["id"] for row in active}
    # Different unresolved values mean latest collection date cannot decide.
    if (
        any(row["status"] == "conflict" and row["id"] not in superseded for row in roles)
        or any(not isinstance(row["value"], str) for row in active)
        or len({(row["field"], row["value"]) for row in active if isinstance(row["value"], str)})
        != 1
    ):
        current_ids = set()
    dates = {item["replacement_id"]: item["effective_date"] for item in valid}
    if len({dates[identifier] for identifier in current_ids}) > 1:
        current_ids = set()
    return [
        {
            **dict(row),
            "claim_id": row["id"],
            "event_at": datetime.combine(dates[row["id"]], time.min, UTC)
            if row["id"] in current_ids
            else None,
            "freshness": "historical"
            if row["id"] in superseded
            else "current"
            if row["id"] in current_ids
            else "unknown",
        }
        for row in roles
    ]
