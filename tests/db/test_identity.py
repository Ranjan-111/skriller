from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from skriller.db import ResearchRepository, WorkspaceAccessDenied, WorkspaceRepository
from skriller.qualification.identity import (
    compare,
    group_claims,
    group_members,
    identity_events,
    reverse_link,
    review_link,
    suggest,
)

pytestmark = pytest.mark.integration_db


def setup(database, kind="person"):
    actor = "identity-" + uuid4().hex
    workspace = database.create_workspace(actor, "Identity")["id"]
    with database.tenant(actor, workspace) as session:
        a = ResearchRepository.entity(session, kind, "Same Name")
        b = ResearchRepository.entity(session, kind, "Same Name")
    return actor, workspace, a["id"], b["id"]


def fact(session, entity, field, value, status="accepted", expired=False):
    ev = ResearchRepository.add_evidence(
        session,
        source_url="https://example.org",
        source_platform="web",
        collected_at=datetime.now(UTC),
        excerpt=value,
        expires_at=datetime.now(UTC) - timedelta(seconds=1) if expired else None,
    )
    return ResearchRepository.claim(
        session, entity, field, value, mode="observed", status=status, evidence_ids=[ev["id"]]
    )


def test_same_name_different_firms_stays_suggestion(database):
    actor, workspace, a, b = setup(database)
    with database.tenant(actor, workspace) as session:
        fact(session, a, "domain", "first.example.org")
        fact(session, b, "domain", "second.example.org")
        assert not compare(session, a, b).eligible
        result = suggest(session, a, b)
        assert review_link(session, result["id"])["state"] == "suggestion"
        assert group_members(session, a) == (a,)


def test_review_reversal_preserves_original_claims_and_append_only_history(database):
    actor, workspace, a, b = setup(database)
    with database.tenant(actor, workspace) as session:
        first = fact(session, a, "native_id.linkedin", "SameID")
        second = fact(session, b, "native_id.linkedin", "SameID")
        result = suggest(session, a, b)
        assert group_members(session, a) == (a,)
        assert review_link(session, result["id"])["state"] == "linked"
        combined = group_claims(session, a)
        assert {item["id"] for item in combined} == {first["id"], second["id"]}
        assert {item["entity_id"] for item in combined} == {a, b}
        reverse_link(session, result["id"])
        reverse_link(session, result["id"])
        assert group_members(session, a) == (a,)
        assert [item["id"] for item in group_claims(session, a)] == [first["id"]]
        assert [item["id"] for item in group_claims(session, b)] == [second["id"]]
        events = (
            session.execute(
                sa.select(identity_events.c.action)
                .where(identity_events.c.review_id == result["id"])
                .order_by(identity_events.c.created_at, identity_events.c.id)
            )
            .scalars()
            .all()
        )
        assert set(events) == {"suggested", "linked", "reversed"} and len(events) == 3
    with pytest.raises(DBAPIError), database.tenant(actor, workspace) as session:
        session.execute(sa.delete(identity_events))


@pytest.mark.parametrize("status,expired", [("unverified", False), ("accepted", True)])
def test_unverified_or_expired_native_ids_do_not_link(database, status, expired):
    actor, workspace, a, b = setup(database)
    with database.tenant(actor, workspace) as session:
        for entity in (a, b):
            fact(session, entity, "native_id.linkedin", "SameID", status, expired)
        assert not compare(session, a, b).eligible


def test_conflicting_native_ids_and_case_sensitive_ids_stay_suggestions(database):
    actor, workspace, a, b = setup(database)
    with database.tenant(actor, workspace) as session:
        fact(session, a, "native_id.linkedin", "ID")
        fact(session, b, "native_id.linkedin", "id")
        assert compare(session, a, b).reason == "native_id_conflict"
        for entity in (a, b):
            fact(session, entity, "native_id.github", "same")
        assert compare(session, a, b).reason == "native_id_conflict"


def test_company_domain_requires_corroboration(database):
    actor, workspace, a, b = setup(database, "company")
    with database.tenant(actor, workspace) as session:
        fact(session, a, "domain", "https://www.example.org/")
        fact(session, b, "domain", "example.org")
        assert not compare(session, a, b).eligible
        for entity in (a, b):
            fact(session, entity, "legal_name", "Example Inc")
            fact(session, entity, "country", "India")
        assert compare(session, a, b).reason == "domain_corroborated"


def test_cross_workspace_and_member_review_denied(database):
    actor, workspace, a, b = setup(database)
    other_actor, other_workspace, other, _ = setup(database)
    with database.tenant(actor, workspace) as session:
        with pytest.raises(LookupError):
            suggest(session, a, other)
        member = "member-" + uuid4().hex
        WorkspaceRepository.add_member(session, member)
        proposal = suggest(session, a, b)
    with pytest.raises(WorkspaceAccessDenied), database.tenant(member, workspace) as session:
        review_link(session, proposal["id"])
    with database.tenant(other_actor, other_workspace) as session:
        with pytest.raises(LookupError):
            reverse_link(session, proposal["id"])
        assert session.execute(sa.select(identity_events)).all() == []


def test_approval_rechecks_facts_changed_since_suggestion(database):
    actor, workspace, a, b = setup(database)
    with database.tenant(actor, workspace) as session:
        for entity in (a, b):
            fact(session, entity, "native_id.linkedin", "same")
        proposal = suggest(session, a, b)
        fact(session, b, "native_id.linkedin", "different")
        assert review_link(session, proposal["id"])["state"] == "suggestion"


def test_transitive_group_conflict_cannot_merge_through_middle_record(database):
    actor, workspace, a, b = setup(database)
    with database.tenant(actor, workspace) as session:
        c = ResearchRepository.entity(session, "person", "Same Name")["id"]
        fact(session, a, "native_id.linkedin", "first")
        fact(session, c, "native_id.linkedin", "different")
        fact(session, a, "native_id.github", "shared-ab")
        fact(session, b, "native_id.github", "shared-ab")
        fact(session, b, "native_id.reddit", "shared-bc")
        fact(session, c, "native_id.reddit", "shared-bc")
        first = suggest(session, a, b)
        assert review_link(session, first["id"])["state"] == "linked"
        second = suggest(session, b, c)
        assert review_link(session, second["id"])["review_outcome"] == "group_identity_conflict"
        assert set(group_members(session, a)) == {a, b}
        assert group_members(session, c) == (c,)
