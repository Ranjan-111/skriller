import pytest
from test_exports import fixture
from test_identity import fact

from skriller.contracts import SearchPlan
from skriller.crm.salesforce import prepare_leads
from skriller.db import ConversationRepository, WorkspaceAccessDenied, WorkspaceRepository
from skriller.erasure import erase
from skriller.storage import BlobUnavailable

pytestmark = pytest.mark.integration_db
MAPPING = {"last_name": "LastName", "company": "Company", "professional_email": "Email"}


def crm_fixture(database, tmp_path):
    actor, workspace, a, b, plan_id, storage = fixture(database, tmp_path)
    with database.tenant(actor, workspace) as session:
        original = ConversationRepository.get_plan(session, plan_id)
        plan = SearchPlan.model_validate(original["interpretation"]).model_copy(
            update={
                "revision": 2,
                "requested_fields": ["last_name", "company", "professional_email"],
            }
        )
        revised = ConversationRepository.revise_plan(
            session,
            original["conversation_id"],
            plan.model_dump(mode="json"),
            parent_id=plan_id,
        )
        for entity in [a, b]:
            fact(session, entity, "last_name", "東京")
            fact(session, entity, "company", "Fixture Ltd")
            fact(
                session, entity, "professional_email", "unverified@example.org", status="unverified"
            )
    return actor, workspace, a, b, revised["id"], storage


def test_real_export_path_preserves_fit_and_blocks_unverified_email(database, tmp_path):
    actor, workspace, a, b, plan, storage = crm_fixture(database, tmp_path)
    with database.tenant(actor, workspace) as session:
        results = prepare_leads(
            session, storage, plan, (a, b), field_map=MAPPING, selected_near_ids=(b,), opt_in=True
        )
        assert [r.fields["Skriller_Fit__c"] for r in results] == ["confirmed", "near_match"]
        assert all("Email" not in row.fields for row in results)
        assert results == prepare_leads(
            session, storage, plan, (a, b), field_map=MAPPING, selected_near_ids=(b,), opt_in=True
        )
        with pytest.raises(ValueError, match="Only confirmed"):
            prepare_leads(session, storage, plan, (b,), field_map=MAPPING, opt_in=True)


def test_erasure_before_preparation_denies_queued_entity_selection(database, tmp_path):
    actor, workspace, a, _, plan, storage = crm_fixture(database, tmp_path)
    queued_selection = (a,)
    with database.tenant(actor, workspace) as session:
        erase(session, storage, a, request_key="crm-fixture-erasure")
    with database.tenant(actor, workspace) as session, pytest.raises(BlobUnavailable):
        prepare_leads(session, storage, plan, queued_selection, field_map=MAPPING, opt_in=True)


def test_owner_opt_in_and_tenant_scope_required(database, tmp_path):
    actor, workspace, a, _, plan, storage = crm_fixture(database, tmp_path)
    with database.tenant(actor, workspace) as session:
        with pytest.raises(ValueError, match="opt-in"):
            prepare_leads(session, storage, plan, (a,), field_map=MAPPING)
        WorkspaceRepository.add_member(session, actor + "-member")
    with (
        database.tenant(actor + "-member", workspace) as session,
        pytest.raises(WorkspaceAccessDenied),
    ):
        prepare_leads(session, storage, plan, (a,), field_map=MAPPING, opt_in=True)
    other = database.create_workspace(actor, "Other CRM scope")["id"]
    with database.tenant(actor, other) as session, pytest.raises(BlobUnavailable):
        prepare_leads(session, storage, plan, (a,), field_map=MAPPING, opt_in=True)
