from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from test_identity import fact, setup

from skriller.contracts import Criterion, SearchPlan
from skriller.db import ResearchRepository, WorkspaceAccessDenied
from skriller.db.schema import claim_evidence, claims, evidence
from skriller.qualification.criteria import rank
from skriller.qualification.identity import reverse_link, review_link, suggest
from skriller.qualification.service import load_facts, qualify_entity

pytestmark = pytest.mark.integration_db


def plan(workspace, **values):
    return SearchPlan(
        workspace_id=UUID(workspace),
        conversation_id=uuid4(),
        revision=1,
        entity_type="person",
        **values,
    )


def test_current_role_projection_keeps_history_out_of_qualification(database):
    from test_contacts import dated, reviewed_roles

    from skriller.qualification.contacts import record_role_refresh

    actor, workspace, entity, _ = setup(database)
    with database.tenant(actor, workspace) as session:
        old = dated(session, entity, "Founder", "2020-01-01")
        new = dated(session, entity, "Advisor", "2025-01-01")
        reviewed_roles(session, old, new)
        assert (
            qualify_entity(
                session,
                plan(
                    workspace,
                    must_have=[Criterion(field="current_role", operator="eq", value="Advisor")],
                ),
                entity,
            ).status
            == "near_match"
        )
        record_role_refresh(session, old, new)
        facts = load_facts(session, entity, now=datetime.now(UTC))
        roles = [item for item in facts if item.field == "current_role"]
        assert len(roles) == 1 and roles[0].value == "Advisor"
        assert roles[0].event_at == datetime(2025, 1, 1, tzinfo=UTC)
        assert (
            qualify_entity(
                session,
                plan(
                    workspace,
                    must_have=[Criterion(field="current_role", operator="eq", value="Advisor")],
                ),
                entity,
            ).status
            == "confirmed"
        )
        assert (
            qualify_entity(
                session,
                plan(
                    workspace,
                    must_have=[Criterion(field="current_role", operator="eq", value="Founder")],
                ),
                entity,
            ).status
            == "near_match"
        )


def test_location_with_unknown_company_size_stays_near_match(database):
    actor, workspace, a, _ = setup(database)
    with database.tenant(actor, workspace) as session:
        fact(session, a, "location", "India")
        selected = plan(
            workspace,
            must_have=[
                Criterion(field="location", operator="eq", value="India"),
                Criterion(field="company_size", operator="gte", value=20),
            ],
        )
        result = qualify_entity(session, selected, a)
        assert result.status == "near_match"
        assert [item.outcome for item in result.essential] == ["matched", "unknown"]


def test_reviewed_identity_and_reversal_change_projection_without_rewriting_claims(database):
    actor, workspace, a, b = setup(database)
    with database.tenant(actor, workspace) as session:
        for entity in (a, b):
            fact(session, entity, "native_id.linkedin", "person:same")
        location = fact(session, b, "location", "India")
        selected = plan(
            workspace, must_have=[Criterion(field="location", operator="eq", value="India")]
        )
        assert qualify_entity(session, selected, a).status == "near_match"
        review = suggest(session, a, b)
        review_link(session, review["id"])
        assert qualify_entity(session, selected, a).status == "confirmed"
        reverse_link(session, review["id"])
        assert qualify_entity(session, selected, a).status == "near_match"
        assert qualify_entity(session, selected, b).status == "confirmed"
        assert (
            session.execute(
                sa.select(claims.c.entity_id).where(claims.c.id == location["id"])
            ).scalar_one()
            == b
        )


def test_every_linked_evidence_must_be_current_and_oldest_controls_freshness(database):
    actor, workspace, a, _ = setup(database)
    with database.tenant(actor, workspace) as session:
        value = fact(session, a, "location", "India")
        old = ResearchRepository.add_evidence(
            session,
            source_url="https://example.org/old",
            source_platform="web",
            collected_at=datetime.now(UTC) - timedelta(days=40),
            excerpt="India",
        )
        session.execute(
            sa.insert(claim_evidence).values(
                workspace_id=workspace, claim_id=value["id"], evidence_id=old["id"]
            )
        )
        selected = plan(
            workspace,
            freshness_days=30,
            must_have=[Criterion(field="location", operator="eq", value="India")],
        )
        assert qualify_entity(session, selected, a).status == "near_match"
        session.execute(
            sa.update(evidence)
            .where(evidence.c.id == old["id"])
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        assert load_facts(session, a, now=datetime.now(UTC)) == ()


def test_collection_date_does_not_establish_hiring_event_date(database):
    actor, workspace, a, _ = setup(database)
    with database.tenant(actor, workspace) as session:
        fact(session, a, "hiring", True)
        selected = plan(
            workspace, must_have=[Criterion(field="hiring", operator="recent", value=7)]
        )
        assert qualify_entity(session, selected, a).essential[0].outcome == "unknown"


def test_conflicting_claims_cannot_confirm(database):
    actor, workspace, a, _ = setup(database)
    with database.tenant(actor, workspace) as session:
        fact(session, a, "location", "India")
        fact(session, a, "location", "USA")
        selected = plan(
            workspace, must_have=[Criterion(field="location", operator="eq", value="India")]
        )
        assert qualify_entity(session, selected, a).essential[0].outcome == "unknown"
        assert all(
            item.status == "unverified" for item in load_facts(session, a, now=datetime.now(UTC))
        )


def test_tenant_scope_and_inaccessible_entity_are_denied(database):
    actor, workspace, a, _ = setup(database)
    _, other_workspace, other, _ = setup(database)
    with database.tenant(actor, workspace) as session:
        with pytest.raises(WorkspaceAccessDenied):
            qualify_entity(session, plan(other_workspace), a)
        with pytest.raises(LookupError):
            qualify_entity(session, plan(workspace), other)
        assert (
            session.execute(
                sa.select(evidence).where(evidence.c.workspace_id == other_workspace)
            ).all()
            == []
        )


def test_preferences_rank_after_fit_status(database):
    actor, workspace, a, b = setup(database)
    with database.tenant(actor, workspace) as session:
        fact(session, a, "location", "India")
        fact(session, b, "location", "India")
        fact(session, b, "role", "Founder")
        selected = plan(
            workspace,
            must_have=[Criterion(field="location", operator="eq", value="India")],
            preferences=[Criterion(field="role", operator="eq", value="Founder")],
        )
        fits = (
            (a, qualify_entity(session, selected, a)),
            (b, qualify_entity(session, selected, b)),
        )
        assert all(item[1].status == "confirmed" for item in fits)
        assert rank(fits)[0][0] == b


def test_cross_tenant_evidence_cannot_be_associated(database):
    from sqlalchemy.exc import DBAPIError

    actor, workspace, a, _ = setup(database)
    other_actor, other_workspace, other, _ = setup(database)
    with database.tenant(other_actor, other_workspace) as session:
        foreign = fact(session, other, "location", "India")
        foreign_evidence = session.execute(
            sa.select(claim_evidence.c.evidence_id).where(
                claim_evidence.c.claim_id == foreign["id"]
            )
        ).scalar_one()
    with database.tenant(actor, workspace) as session:
        local = fact(session, a, "location", "India")
    with pytest.raises(DBAPIError), database.tenant(actor, workspace) as session:
        session.execute(
            sa.insert(claim_evidence).values(
                workspace_id=workspace, claim_id=local["id"], evidence_id=foreign_evidence
            )
        )


def test_claim_budget_is_enforced_before_fact_conversion(database):
    actor, workspace, a, _ = setup(database)
    with database.tenant(actor, workspace) as session:
        session.execute(
            sa.insert(claims),
            [
                {
                    "workspace_id": workspace,
                    "entity_id": a,
                    "field": "unused",
                    "value": None,
                    "mode": "unavailable",
                    "status": "unverified",
                }
                for _ in range(301)
            ],
        )
        with pytest.raises(ValueError, match="pilot bounds"):
            qualify_entity(session, plan(workspace), a)


def test_missing_evidence_excerpt_and_inferred_claim_are_unknown(database):
    actor, workspace, a, _ = setup(database)
    with database.tenant(actor, workspace) as session:
        ev = ResearchRepository.add_evidence(
            session,
            source_url="https://example.org",
            source_platform="web",
            collected_at=datetime.now(UTC),
            excerpt=None,
        )
        ResearchRepository.claim(
            session,
            a,
            "location",
            "India",
            mode="observed",
            status="accepted",
            evidence_ids=[ev["id"]],
        )
        valid = ResearchRepository.add_evidence(
            session,
            source_url="https://example.org",
            source_platform="web",
            collected_at=datetime.now(UTC),
            excerpt="Founder",
        )
        ResearchRepository.claim(
            session,
            a,
            "role",
            "Founder",
            mode="inferred",
            status="accepted",
            evidence_ids=[valid["id"]],
        )
        assert load_facts(session, a, now=datetime.now(UTC)) == ()
