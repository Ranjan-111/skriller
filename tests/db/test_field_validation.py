from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict

from skriller.db import ResearchRepository
from skriller.db.schema import evidence
from skriller.extraction.adaptive import ValidatedField
from skriller.extraction.validation import Citation, FieldBinding, validate_extraction


class Facts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str | None = None
    employees: int | None = None


def setup(database):
    actor = f"field-validation-{uuid4()}"
    workspace = database.create_workspace(actor, "Validation fixture")["id"]
    with database.tenant(actor, workspace) as session:
        entity = ResearchRepository.entity(session, "company", "Aurora")
    return actor, workspace, UUID(entity["id"])


def save(session, quote, *, expired=False):
    return ResearchRepository.add_evidence(
        session,
        source_url="https://example.org/company",
        source_platform="web",
        collected_at=datetime.now(UTC),
        excerpt=quote,
        content_hash=sha256(quote.encode()).hexdigest(),
        expires_at=datetime.now(UTC) - timedelta(seconds=1) if expired else None,
    )


def test_invented_wellformed_email_and_wrong_type_never_accepted(database):
    actor, workspace, entity = setup(database)
    with database.tenant(actor, workspace) as session:
        saved = save(session, "Aurora employs 25 staff. Contact not stated.")
        citations = {"email": Citation((UUID(saved["id"]),), saved["excerpt"])}
        checked = validate_extraction(
            session,
            entity,
            '{"email":"invented@example.org"}',
            Facts,
            citations=citations,
            persist=True,
        )
        assert checked.schema_valid
        assert checked.fields["email"].value is None
        assert checked.fields["email"].reason == "value_missing"
        assert checked.fields["email"].status == "unverified"
        wrong = validate_extraction(session, entity, {"employees": "25"}, Facts, citations={})
        assert not wrong.schema_valid and wrong.fields["employees"].reason == "schema_invalid"
        claims = ResearchRepository.claims_for(session, str(entity))
        assert all(claim["value"] is None for claim in claims)


def test_missing_cross_tenant_expired_and_deleted_evidence_rejected(database):
    actor, workspace, entity = setup(database)
    foreign_actor, foreign_workspace, _ = setup(database)
    with database.tenant(foreign_actor, foreign_workspace) as session:
        foreign = save(session, "public@example.org")
    with database.tenant(actor, workspace) as session:
        expired = save(session, "public@example.org", expired=True)
        deleted = save(session, "public@example.org")
        session.execute(sa.delete(evidence).where(evidence.c.id == deleted["id"]))
        for identifier in [uuid4(), UUID(foreign["id"]), UUID(expired["id"]), UUID(deleted["id"])]:
            checked = validate_extraction(
                session,
                entity,
                {"email": "public@example.org"},
                Facts,
                citations={"email": Citation((identifier,), "public@example.org")},
                persist=True,
            )
            assert checked.fields["email"].value is None
            assert checked.fields["email"].reason == "evidence_unavailable"


def test_literal_value_needs_trusted_subject_mapping_and_matching_hash(database):
    actor, workspace, entity = setup(database)
    with database.tenant(actor, workspace) as session:
        saved = save(session, "Aurora employs 25 staff. public@example.org")
        citation = Citation((UUID(saved["id"]),), saved["excerpt"])
        checked = validate_extraction(
            session, entity, {"employees": 25}, Facts, citations={"employees": citation}
        )
        assert checked.fields["employees"].status == "unverified"
        semantic = ValidatedField(
            "accepted",
            "validated_direct",
            saved["content_hash"],
            quote="25",
            locator="/html/body/p[1]",
            template_version=1,
        )
        binding = FieldBinding(entity, "employees", semantic)
        accepted = validate_extraction(
            session,
            entity,
            {"employees": 25},
            Facts,
            citations={"employees": citation},
            bindings={"employees": binding},
            persist=True,
        )
        assert accepted.fields["employees"].status == "accepted"
        wrong_subject = FieldBinding(uuid4(), "employees", semantic)
        rejected = validate_extraction(
            session,
            entity,
            {"employees": 25},
            Facts,
            citations={"employees": citation},
            bindings={"employees": wrong_subject},
        )
        assert rejected.fields["employees"].value is None
        assert rejected.fields["employees"].reason == "subject_relationship_mismatch"


def test_numeric_boundaries_and_contact_inferences_rejected(database):
    actor, workspace, entity = setup(database)
    with database.tenant(actor, workspace) as session:
        saved = save(session, "Aurora employs 250 staff. public@example.org")
        citation = Citation((UUID(saved["id"]),), saved["excerpt"])
        checked = validate_extraction(
            session, entity, {"employees": 25}, Facts, citations={"employees": citation}
        )
        assert checked.fields["employees"].reason == "value_missing"
        inferred = Citation((UUID(saved["id"]),), saved["excerpt"], mode="inferred")
        checked = validate_extraction(
            session, entity, {"email": "invented@example.org"}, Facts, citations={"email": inferred}
        )
        assert checked.fields["email"].value is None
        assert checked.fields["email"].reason == "contact_inference_rejected"
