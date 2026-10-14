from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from skriller.contracts import Criterion, SearchPlan
from skriller.db import (
    ConversationRepository,
    ResearchRepository,
    WorkspaceAccessDenied,
    WorkspaceRepository,
)
from skriller.db.schema import claims, suppressions
from skriller.lists import create_list, list_snapshots, refresh_list, snapshot
from skriller.qualification.contacts import DatedRole, record_role_refresh
from skriller.qualification.identity import review_link, suggest


def setup(database):
    actor = f"list-{uuid4()}"
    workspace = database.create_workspace(actor, "Saved list fixture")["id"]
    with database.tenant(actor, workspace) as session:
        entity = ResearchRepository.entity(session, "person", "Fixture Person")["id"]
        conversation = ConversationRepository.create(session, "Fixture plan")
        plan = SearchPlan(
            workspace_id=UUID(workspace),
            conversation_id=UUID(conversation["id"]),
            revision=1,
            entity_type="person",
            must_have=[Criterion(field="current_role", operator="eq", value="Director")],
        )
        persisted = ConversationRepository.revise_plan(
            session, conversation["id"], plan.model_dump(mode="json")
        )
    return actor, workspace, entity, persisted["id"]


def fact(
    session,
    entity,
    field,
    value,
    *,
    url="https://example.org/profile",
    status="accepted",
    excerpt=None,
):
    ev = ResearchRepository.add_evidence(
        session,
        source_url=url,
        source_platform="web",
        collected_at=datetime.now(UTC),
        excerpt=excerpt or value,
    )
    claim = ResearchRepository.claim(
        session, entity, field, value, mode="observed", status=status, evidence_ids=[ev["id"]]
    )
    return claim["id"], ev["id"]


def role(session, entity, value, effective):
    claim, ev = fact(
        session, entity, "current_role", value, excerpt=f"{value}; effective {effective}"
    )
    dating = ResearchRepository.claim(
        session,
        entity,
        "role_effective_date",
        effective,
        mode="observed",
        status="accepted",
        evidence_ids=[ev],
    )
    return DatedRole(claim, dating["id"], ev)


def suppress(session, actor, entity, kind="entity"):
    session.execute(
        sa.insert(suppressions).values(
            workspace_id=session.info["workspace_id"],
            id=str(uuid4()),
            kind=kind,
            key=entity,
            reason="fixture opt-out",
            created_by=actor,
        )
    )


def test_role_refresh_keeps_previous_immutable_snapshot_and_evidence(database):
    actor, workspace, entity, plan = setup(database)
    with database.tenant(actor, workspace) as session:
        old = role(session, entity, "Engineer", "2024-01-01")
        middle = role(session, entity, "Director", "2025-01-01")
        session.execute(
            sa.update(claims)
            .where(
                claims.c.id.in_(
                    [
                        old.role_claim_id,
                        middle.role_claim_id,
                        old.date_claim_id,
                        middle.date_claim_id,
                    ]
                )
            )
            .values(status="accepted")
        )
        assert record_role_refresh(session, old, middle) == "superseded"
        saved = create_list(session, "Fixture list", plan, (entity,))
        before = snapshot(session, saved["id"], 1)
        assert before["payload"]["members"][0]["fit"]["status"] == "confirmed"
        newer = role(session, entity, "VP", "2026-01-01")
        session.execute(
            sa.update(claims)
            .where(
                claims.c.id.in_(
                    [
                        old.role_claim_id,
                        middle.role_claim_id,
                        newer.role_claim_id,
                        old.date_claim_id,
                        middle.date_claim_id,
                        newer.date_claim_id,
                    ]
                )
            )
            .values(status="accepted")
        )
        assert record_role_refresh(session, middle, newer) == "superseded"
        refreshed = refresh_list(session, saved["id"], (entity,), expected_revision=1)
        assert refreshed["revision"] == 2
        assert refreshed["payload"]["members"][0]["fit"]["status"] != "confirmed"
        assert snapshot(session, saved["id"], 1) == before
        old_values = before["payload"]["members"][0]["values"]
        assert any(value["value"] == "Director" and value["evidence"] for value in old_values)
    with pytest.raises(sa.exc.DBAPIError), database.tenant(actor, workspace) as session:
        session.execute(sa.update(list_snapshots).values(payload={}))


def test_suppression_blocks_reviewed_alias_under_different_url(database):
    actor, workspace, entity, plan = setup(database)
    with database.tenant(actor, workspace) as session:
        alias = ResearchRepository.entity(session, "person", "Fixture Alias")["id"]
        fact(
            session,
            entity,
            "native_id.linkedin",
            "native-fixture",
            url="https://linkedin.com/in/old-url",
        )
        fact(
            session,
            alias,
            "native_id.linkedin",
            "native-fixture",
            url="https://linkedin.com/in/new-url",
        )
        review_link(session, suggest(session, entity, alias)["id"])
        saved = create_list(session, "Alias list", plan, (alias,))
        assert len(snapshot(session, saved["id"], 1)["payload"]["members"]) == 1
        suppress(session, actor, entity)
        refreshed = refresh_list(session, saved["id"], (alias,), expected_revision=1)
        assert refreshed["payload"]["members"] == []
        assert refreshed["payload"]["omitted"] == [{"entity_id": alias, "reason": "suppressed"}]
        assert len(snapshot(session, saved["id"], 1)["payload"]["members"]) == 1


def test_profile_suppression_matches_proven_native_identity_without_merging(database):
    actor, workspace, entity, plan = setup(database)
    with database.tenant(actor, workspace) as session:
        alias = ResearchRepository.entity(session, "person", "Other URL")["id"]
        fact(
            session,
            entity,
            "native_id.linkedin",
            "native-fixture",
            url="https://linkedin.com/in/old-url",
        )
        fact(
            session,
            alias,
            "native_id.linkedin",
            "native-fixture",
            url="https://linkedin.com/in/new-url",
        )
        suppress(session, actor, "https://linkedin.com/in/old-url", kind="profile")
        saved = create_list(session, "Profile list", plan, (alias,))
        assert snapshot(session, saved["id"], 1)["payload"]["members"] == []


def test_unverified_identity_is_not_automerged_or_promoted(database):
    actor, workspace, entity, plan = setup(database)
    with database.tenant(actor, workspace) as session:
        alias = ResearchRepository.entity(session, "person", "Same display name")["id"]
        fact(session, entity, "native_id.linkedin", "native-fixture")
        fact(session, alias, "native_id.linkedin", "native-fixture", status="unverified")
        suppress(session, actor, entity)
        saved = create_list(session, "Unverified list", plan, (alias,))
        item = snapshot(session, saved["id"], 1)["payload"]["members"][0]
        assert item["fit"]["status"] == "near_match"
        assert item["identity_status"] == "suppression_unresolved"
        assert item["values"] == []


def test_owner_refresh_member_read_foreign_scope_and_stale_revision(database):
    actor, workspace, entity, plan = setup(database)
    member = f"member-{uuid4()}"
    with database.tenant(actor, workspace) as session:
        saved = create_list(session, "Access list", plan, (entity,))
        WorkspaceRepository.add_member(session, member)
        with pytest.raises(ValueError):
            refresh_list(session, saved["id"], (entity,), expected_revision=0)
        with pytest.raises(ValueError):
            refresh_list(session, saved["id"], (entity, entity), expected_revision=1)
    with database.tenant(member, workspace) as session:
        assert snapshot(session, saved["id"], 1)["revision"] == 1
        with pytest.raises(WorkspaceAccessDenied):
            refresh_list(session, saved["id"], (entity,), expected_revision=1)
    other = database.create_workspace(actor, "Separate list fixture")["id"]
    with database.tenant(actor, other) as session:
        with pytest.raises(LookupError):
            snapshot(session, saved["id"], 1)
        with pytest.raises(LookupError):
            create_list(session, "Foreign plan", plan, ())


def test_generic_email_not_snapshotted_and_professional_ownership_not_shared(database):
    actor, workspace, entity, plan = setup(database)
    with database.tenant(actor, workspace) as session:
        fact(session, entity, "email", "generic@company.example")
        fact(session, entity, "work_email", "person@company.example")
        saved = create_list(session, "Contact list", plan, (entity,))
        values = snapshot(session, saved["id"], 1)["payload"]["members"][0]["values"]
        assert any(item["value"] == "person@company.example" for item in values)
        assert not any(item["value"] == "generic@company.example" for item in values)
        alias = ResearchRepository.entity(session, "person", "Review Alias")["id"]
        fact(session, entity, "native_id.linkedin", "native-contact-fixture")
        fact(session, alias, "native_id.linkedin", "native-contact-fixture")
        review_link(session, suggest(session, entity, alias)["id"])
        refreshed = refresh_list(session, saved["id"], (alias,), expected_revision=1)
        assert not any(
            item["field"] == "work_email" for item in refreshed["payload"]["members"][0]["values"]
        )


def test_oversized_refresh_fails_without_rewriting_previous_revision(database):
    actor, workspace, entity, plan = setup(database)
    with database.tenant(actor, workspace) as session:
        saved = create_list(session, "Bounded list", plan, (entity,))
        before = snapshot(session, saved["id"], 1)
        for index in range(31):
            fact(session, entity, f"field_{index}", "fixture")
        with pytest.raises(ValueError, match="fact bounds"):
            refresh_list(session, saved["id"], (entity,), expected_revision=1)
        assert snapshot(session, saved["id"], 1) == before
        assert (
            session.execute(sa.select(sa.func.count()).select_from(list_snapshots)).scalar_one()
            == 1
        )
