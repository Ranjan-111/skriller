from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa

from skriller.db import ResearchRepository
from skriller.db.schema import claims, evidence
from skriller.qualification.contacts import (
    DatedRole,
    check_contact,
    email_domain,
    record_role_refresh,
    role_history,
    role_projection,
)


def setup(database):
    actor = f"contacts-{uuid4()}"
    workspace = database.create_workspace(actor, "Contacts fixture")["id"]
    with database.tenant(actor, workspace) as session:
        entity = ResearchRepository.entity(session, "person", "Person Fixture")["id"]
    return actor, workspace, entity


def fact(session, entity, field, value, *, excerpt=None, status="accepted", mode="observed"):
    ev = ResearchRepository.add_evidence(
        session,
        source_url="https://example.org/team",
        source_platform="web",
        collected_at=datetime.now(UTC),
        excerpt=excerpt or value,
    )
    claim = ResearchRepository.claim(
        session, entity, field, value, status=status, mode=mode, evidence_ids=[ev["id"]]
    )
    return claim["id"], ev["id"]


def dated(session, entity, role, effective):
    claim, ev = fact(
        session, entity, "current_role", role, excerpt=f"{role}; effective {effective}"
    )
    dating = ResearchRepository.claim(
        session,
        entity,
        "role_effective_date",
        effective,
        status="accepted",
        mode="observed",
        evidence_ids=[ev],
    )
    return DatedRole(claim, dating["id"], ev)


def reviewed_roles(session, *observations):
    # Explicit trusted-review fixture: raw refresh insertion first creates
    # conflicts. Production needs reviewed subject/date bindings before this
    # decision; this component never silently accepts those conflicts.
    ids = [
        identifier
        for item in observations
        for identifier in (item.role_claim_id, item.date_claim_id)
    ]
    session.execute(sa.update(claims).where(claims.c.id.in_(ids)).values(status="accepted"))


@pytest.mark.parametrize(
    "email", ["name@company.example", "a+b@sub.company.example", "person@bücher.example"]
)
def test_supported_professional_syntax(email):
    assert email_domain(email) is not None


@pytest.mark.parametrize(
    "email",
    [
        "name",
        ".name@example.org",
        "name..last@example.org",
        "name@localhost",
        "name@127.0.0.1",
        "name@evil.example/path",
        "name@example.org\nBcc:x",
        "name@-bad.example",
        "x@a..org",
        "x@metadata.google.internal",
    ],
)
def test_unsupported_or_unsafe_address_syntax(email):
    assert email_domain(email) is None


def test_mx_does_not_verify_mailbox_or_unproven_ownership(database):
    actor, workspace, entity = setup(database)
    with database.tenant(actor, workspace) as session:
        result = check_contact(session, entity, "person@company.example", mx_status="present")
        assert result.syntax_status == "valid"
        assert result.domain_status == "mx_present"
        assert result.ownership_status == "unverified"
        assert result.email is None and result.mailbox_status == "not_checked"


def test_only_accepted_published_professional_contact_is_exposed(database):
    actor, workspace, entity = setup(database)
    with database.tenant(actor, workspace) as session:
        claim, ev = fact(session, entity, "work_email", "person@company.example")
        result = check_contact(
            session, entity, "person@company.example", claim_id=claim, evidence_id=ev
        )
        assert result.email == "person@company.example"
        assert result.ownership_status == "published_professional"
        assert result.domain_status == "not_checked" and result.mailbox_status == "not_checked"
        generic, generic_ev = fact(session, entity, "email", "person@company.example")
        assert (
            check_contact(
                session, entity, "person@company.example", claim_id=generic, evidence_id=generic_ev
            ).email
            is None
        )
        inferred, inferred_ev = fact(
            session, entity, "work_email", "guessed@company.example", mode="inferred"
        )
        assert (
            check_contact(
                session,
                entity,
                "guessed@company.example",
                claim_id=inferred,
                evidence_id=inferred_ev,
            ).email
            is None
        )
        unverified, unver_ev = fact(
            session, entity, "work_email", "other@company.example", status="unverified"
        )
        assert (
            check_contact(
                session, entity, "other@company.example", claim_id=unverified, evidence_id=unver_ev
            ).email
            is None
        )


def test_expired_contact_wrong_quote_or_other_person_never_inherits_ownership(database):
    actor, workspace, entity = setup(database)
    with database.tenant(actor, workspace) as session:
        other = ResearchRepository.entity(session, "person", "Other Person")["id"]
        claim, ev = fact(session, entity, "work_email", "person@company.example")
        assert (
            check_contact(
                session, other, "person@company.example", claim_id=claim, evidence_id=ev
            ).email
            is None
        )
        session.execute(
            sa.update(evidence)
            .where(evidence.c.id == ev)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        assert (
            check_contact(
                session, entity, "person@company.example", claim_id=claim, evidence_id=ev
            ).email
            is None
        )
        missing, missing_ev = fact(
            session,
            entity,
            "work_email",
            "person@company.example",
            excerpt="Different published data",
        )
        assert (
            check_contact(
                session, entity, "person@company.example", claim_id=missing, evidence_id=missing_ev
            ).email
            is None
        )


def test_dated_refresh_retains_old_claim_as_historical_and_append_only_history(database):
    actor, workspace, entity = setup(database)
    with database.tenant(actor, workspace) as session:
        old = dated(session, entity, "Engineer", "2024-01-01")
        new = dated(session, entity, "Director", "2025-06-01")
        reviewed_roles(session, old, new)
        assert record_role_refresh(session, old, new) == "superseded"
        assert record_role_refresh(session, old, new) == "superseded"
        projection = {row["id"]: row for row in role_projection(session, entity)}
        assert projection[old.role_claim_id]["freshness"] == "historical"
        assert projection[new.role_claim_id]["freshness"] == "current"
        assert projection[new.role_claim_id]["event_at"] == datetime(2025, 6, 1, tzinfo=UTC)
        assert projection[new.role_claim_id]["claim_id"] == new.role_claim_id
        assert projection[old.role_claim_id]["status"] == "accepted"
        assert (
            session.execute(sa.select(sa.func.count()).select_from(role_history)).scalar_one() == 1
        )
        assert (
            session.execute(
                sa.select(claims.c.value).where(claims.c.id == old.role_claim_id)
            ).scalar_one()
            == "Engineer"
        )
    with pytest.raises(sa.exc.DBAPIError), database.tenant(actor, workspace) as session:
        session.execute(sa.delete(role_history))


def test_ambiguous_future_or_cross_person_refresh_remains_unknown(database):
    actor, workspace, entity = setup(database)
    with database.tenant(actor, workspace) as session:
        old = dated(session, entity, "Engineer", "2024-01-01")
        same_date = dated(session, entity, "Director", "2024-01-01")
        reviewed_roles(session, old, same_date)
        assert record_role_refresh(session, old, same_date) == "ambiguous_or_unchanged"
        future = dated(session, entity, "Manager", "2099-01-01")
        assert record_role_refresh(session, old, future) == "unknown_dates_or_evidence"
        other = ResearchRepository.entity(session, "person", "Namesake")["id"]
        other_role = dated(session, other, "Director", "2025-01-01")
        reviewed_roles(session, old, other_role)
        assert record_role_refresh(session, old, other_role) == "identity_or_field_mismatch"
        assert all(row["freshness"] == "unknown" for row in role_projection(session, entity))


def test_conflicting_third_role_and_expired_replacement_cannot_be_current(database):
    actor, workspace, entity = setup(database)
    with database.tenant(actor, workspace) as session:
        old = dated(session, entity, "Engineer", "2024-01-01")
        new = dated(session, entity, "Director", "2025-06-01")
        reviewed_roles(session, old, new)
        assert record_role_refresh(session, old, new) == "superseded"
        fact(session, entity, "current_role", "Consultant")
        assert not any(row["freshness"] == "current" for row in role_projection(session, entity))
        session.execute(
            sa.update(evidence)
            .where(evidence.c.id == new.evidence_id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        assert not any(row["freshness"] == "current" for row in role_projection(session, entity))


def test_foreign_claim_evidence_unavailable_without_tenant_leak(database):
    actor, workspace, entity = setup(database)
    with database.tenant(actor, workspace) as session:
        claim, ev = fact(session, entity, "work_email", "person@company.example")
    other_workspace = database.create_workspace(actor, "Separate fixture")["id"]
    with database.tenant(actor, other_workspace) as session:
        other = ResearchRepository.entity(session, "person", "Other")["id"]
        assert (
            check_contact(
                session, other, "person@company.example", claim_id=claim, evidence_id=ev
            ).email
            is None
        )
        assert role_projection(session, other) == []


def test_unreviewed_refresh_conflicts_are_not_automatically_accepted(database):
    actor, workspace, entity = setup(database)
    with database.tenant(actor, workspace) as session:
        old = dated(session, entity, "Engineer", "2024-01-01")
        new = dated(session, entity, "Director", "2025-06-01")
        assert record_role_refresh(session, old, new) == "unknown_dates_or_evidence"
        assert (
            session.execute(sa.select(sa.func.count()).select_from(role_history)).scalar_one() == 0
        )
        assert all(row["freshness"] == "unknown" for row in role_projection(session, entity))
        assert all(row["status"] == "conflict" for row in role_projection(session, entity))


def test_malformed_json_role_is_unknown_without_breaking_projection(database):
    actor, workspace, entity = setup(database)
    with database.tenant(actor, workspace) as session:
        ev = ResearchRepository.add_evidence(
            session,
            source_url="https://example.org/team",
            source_platform="web",
            collected_at=datetime.now(UTC),
            excerpt="fixture",
        )
        malformed = ResearchRepository.claim(
            session,
            entity,
            "current_role",
            {"unexpected": ["CEO"]},
            mode="observed",
            status="accepted",
            evidence_ids=[ev["id"]],
        )
        projection = role_projection(session, entity)
        assert projection[0]["claim_id"] == malformed["id"]
        assert projection[0]["freshness"] == "unknown" and projection[0]["event_at"] is None


def test_nonpublic_source_url_cannot_establish_published_contact(database):
    actor, workspace, entity = setup(database)
    with database.tenant(actor, workspace) as session:
        claim, ev = fact(session, entity, "work_email", "person@company.example")
        session.execute(
            sa.update(evidence)
            .where(evidence.c.id == ev)
            .values(source_url="http://169.254.169.254/private-contact")
        )
        result = check_contact(
            session, entity, "person@company.example", claim_id=claim, evidence_id=ev
        )
        assert result.email is None and result.reason == "publication_source_invalid"
