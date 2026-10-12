from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from skriller.db.repositories import ConversationRepository, ResearchRepository

pytestmark = pytest.mark.integration_db


def add_evidence(session, source="https://example.test/about"):
    return ResearchRepository.add_evidence(
        session,
        source_url=source,
        source_platform="web",
        collected_at=datetime.now(UTC),
        excerpt="Founder of Acme",
    )


def test_cross_tenant_and_missing_evidence_references_rejected(database):
    actor = str(uuid4())
    a, b = (
        database.create_workspace(actor, "A research"),
        database.create_workspace(actor, "B research"),
    )
    with database.tenant(actor, a["id"]) as session:
        entity = ResearchRepository.entity(session, "person", "Alex")
    with database.tenant(actor, b["id"]) as session:
        other = add_evidence(session)
    for evidence_id in (other["id"], str(uuid4())):
        with pytest.raises(DBAPIError), database.tenant(actor, a["id"]) as session:
            ResearchRepository.claim(
                session,
                entity["id"],
                "role",
                "Founder",
                mode="observed",
                evidence_ids=[evidence_id],
            )
    with database.tenant(actor, a["id"]) as session:
        assert ResearchRepository.claims_for(session, entity["id"]) == []
    with (
        pytest.raises(DBAPIError, match="requires evidence"),
        database.tenant(actor, a["id"]) as session,
    ):
        session.execute(
            sa.text(
                "INSERT INTO claims(workspace_id,id,entity_id,field,value,mode,status) "
                "VALUES(:w,:id,:entity,'role','\"Founder\"','observed','unverified')"
            ),
            {"w": a["id"], "id": str(uuid4()), "entity": entity["id"]},
        )


def test_conflicting_observations_and_unavailable_values_preserved(database):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "Conflicts")
    with database.tenant(actor, workspace["id"]) as session:
        entity = ResearchRepository.entity(session, "person", "Alex")
        first, second = add_evidence(session), add_evidence(session, "https://example.test/team")
        ResearchRepository.claim(
            session,
            entity["id"],
            "role",
            "Founder",
            mode="observed",
            evidence_ids=[first["id"]],
            status="accepted",
        )
        ResearchRepository.claim(
            session, entity["id"], "role", "Engineer", mode="observed", evidence_ids=[second["id"]]
        )
        ResearchRepository.claim(
            session, entity["id"], "email", None, mode="unavailable", evidence_ids=[]
        )
    with database.tenant(actor, workspace["id"]) as session:
        rows = ResearchRepository.claims_for(session, entity["id"])
        roles = [row for row in rows if row["field"] == "role"]
        assert {row["value"] for row in roles} == {"Founder", "Engineer"}
        assert {row["status"] for row in roles} == {"conflict"}
        assert next(row for row in rows if row["field"] == "email")["value"] is None
        with pytest.raises(ValueError, match="null"):
            ResearchRepository.claim(
                session,
                entity["id"],
                "email",
                "invented@example.test",
                mode="unavailable",
                evidence_ids=[],
            )
    with (
        pytest.raises(DBAPIError, match="requires evidence"),
        database.tenant(actor, workspace["id"]) as session,
    ):
        session.execute(
            sa.text("DELETE FROM claim_evidence WHERE evidence_id=:id"), {"id": first["id"]}
        )


def test_qualifications_links_and_suppression_remain_tenant_scoped(database):
    actor = str(uuid4())
    a, b = (
        database.create_workspace(actor, "A qualified"),
        database.create_workspace(actor, "B qualified"),
    )
    with database.tenant(actor, a["id"]) as session:
        company = ResearchRepository.entity(session, "company", "Acme", "acme.test")
        person = ResearchRepository.entity(session, "person", "Alex")
        ResearchRepository.link(session, person["id"], company["id"], "works_at")
        conversation = ConversationRepository.create(session, "Qualify Acme")
        plan = ConversationRepository.revise_plan(
            session, conversation["id"], {"industry": "fintech"}
        )
        citation = add_evidence(session)
        claim = ResearchRepository.claim(
            session,
            company["id"],
            "industry",
            "fintech",
            mode="inferred",
            evidence_ids=[citation["id"]],
        )
        result = ResearchRepository.qualify(
            session,
            company["id"],
            plan["id"],
            "fintech",
            "match",
            reason="Classification from source description",
            claim_id=claim["id"],
        )
        assert result["outcome"] == "match"
        ResearchRepository.suppress(session, "domain", "acme.test", "Customer request")
        assert ResearchRepository.is_suppressed(session, "domain", "acme.test")
    with database.tenant(actor, b["id"]) as session:
        assert not ResearchRepository.is_suppressed(session, "domain", "acme.test")
        assert ResearchRepository.claims_for(session, company["id"]) == []
