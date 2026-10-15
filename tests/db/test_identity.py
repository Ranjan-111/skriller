from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from skriller.db import ResearchRepository, WorkspaceAccessDenied, WorkspaceRepository
from skriller.db.schema import claim_evidence, evidence
from skriller.qualification.identity import (
    compare,
    group_claims,
    group_members,
    identity_events,
    propose_candidates,
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
        first = fact(session, a, "native_id.linkedin", "person:SameID")
        second = fact(session, b, "native_id.linkedin", "person:SameID")
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
            fact(session, entity, "native_id.linkedin", "person:SameID", status, expired)
        assert not compare(session, a, b).eligible


def test_conflicting_native_ids_and_case_sensitive_ids_stay_suggestions(database):
    actor, workspace, a, b = setup(database)
    with database.tenant(actor, workspace) as session:
        fact(session, a, "native_id.linkedin", "person:ID")
        fact(session, b, "native_id.linkedin", "person:id")
        assert compare(session, a, b).reason == "native_id_conflict"
        for entity in (a, b):
            fact(session, entity, "native_id.github", "person:same")
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
            fact(session, entity, "native_id.linkedin", "person:same")
        proposal = suggest(session, a, b)
        fact(session, b, "native_id.linkedin", "person:different")
        assert review_link(session, proposal["id"])["state"] == "suggestion"


def test_transitive_group_conflict_cannot_merge_through_middle_record(database):
    actor, workspace, a, b = setup(database)
    with database.tenant(actor, workspace) as session:
        c = ResearchRepository.entity(session, "person", "Same Name")["id"]
        fact(session, a, "native_id.linkedin", "person:first")
        fact(session, c, "native_id.linkedin", "person:different")
        fact(session, a, "native_id.github", "person:shared-ab")
        fact(session, b, "native_id.github", "person:shared-ab")
        fact(session, b, "native_id.reddit", "person:shared-bc")
        fact(session, c, "native_id.reddit", "person:shared-bc")
        first = suggest(session, a, b)
        assert review_link(session, first["id"])["state"] == "linked"
        second = suggest(session, b, c)
        assert review_link(session, second["id"])["review_outcome"] == "group_identity_conflict"
        assert set(group_members(session, a)) == {a, b}
        assert group_members(session, c) == (c,)


@pytest.mark.parametrize(
    "value", ["SameID", "post:123", "company:123", "person:urn:li:activity:123"]
)
def test_untyped_or_wrong_object_ids_never_identify_a_person(database, value):
    actor, workspace, a, b = setup(database)
    with database.tenant(actor, workspace) as session:
        for entity in (a, b):
            fact(session, entity, "native_id.linkedin", value)
        assert not compare(session, a, b).eligible
        proposal = suggest(session, a, b)
        assert review_link(session, proposal["id"])["state"] == "suggestion"


def test_approved_identity_projection_stops_when_support_is_removed(database):
    actor, workspace, a, b = setup(database)
    with database.tenant(actor, workspace) as session:
        fact(session, a, "native_id.linkedin", "person:stable-id")
        claim = fact(session, b, "native_id.linkedin", "person:stable-id")
        proposal = suggest(session, a, b)
        assert review_link(session, proposal["id"])["state"] == "linked"
        assert set(group_members(session, a)) == {a, b}
        identifier = session.execute(
            sa.select(claim_evidence.c.evidence_id).where(claim_evidence.c.claim_id == claim["id"])
        ).scalar_one()
        session.execute(sa.update(evidence).where(evidence.c.id == identifier).values(excerpt=""))
        assert not compare(session, a, b).eligible
        assert group_members(session, a) == (a,)
        assert set(group_members(session, a, current_only=False)) == {a, b}


def test_any_expired_identity_support_invalidates_the_whole_fact(database):
    actor, workspace, a, b = setup(database)
    with database.tenant(actor, workspace) as session:
        fact(session, a, "native_id.linkedin", "person:stable-id")
        claim = fact(session, b, "native_id.linkedin", "person:stable-id")
        old = ResearchRepository.add_evidence(
            session,
            source_url="https://example.org/old",
            source_platform="web",
            collected_at=datetime.now(UTC),
            excerpt="stable-id",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        session.execute(
            sa.insert(claim_evidence).values(
                workspace_id=workspace, claim_id=claim["id"], evidence_id=old["id"]
            )
        )
        assert not compare(session, a, b).eligible


def test_candidate_suggestions_are_bounded_idempotent_and_never_merge(database):
    actor, workspace, a, b = setup(database)
    with database.tenant(actor, workspace) as session:
        for entity in (a, b):
            fact(session, entity, "native_id.linkedin", "person:stable-id")
        first = propose_candidates(session, [a, b, a])
        assert first["suggestions"] == 1
        assert not first["pair_limit_reached"]
        assert propose_candidates(session, [b, a]) == first
        assert group_members(session, a) == (a,)
        assert (
            session.execute(sa.select(sa.func.count()).select_from(identity_events)).scalar_one()
            == 1
        )
        member = "identity-member-" + uuid4().hex
        WorkspaceRepository.add_member(session, member)
    with database.tenant(member, workspace) as session:
        assert propose_candidates(session, [a, b])["status"] == "owner_review_required"


def test_later_nonadjacent_group_conflict_cannot_transfer_claims(database):
    actor, workspace, a, b = setup(database)
    with database.tenant(actor, workspace) as session:
        c = ResearchRepository.entity(session, "person", "Same Name")["id"]
        for entity in (a, b):
            fact(session, entity, "native_id.github", "person:shared-ab")
        for entity in (b, c):
            fact(session, entity, "native_id.reddit", "person:shared-bc")
        assert review_link(session, suggest(session, a, b)["id"])["state"] == "linked"
        assert review_link(session, suggest(session, b, c)["id"])["state"] == "linked"
        assert set(group_members(session, a)) == {a, b, c}
        fact(session, a, "native_id.linkedin", "person:first")
        fact(session, c, "native_id.linkedin", "person:different")
        assert group_members(session, a) == (a,)
