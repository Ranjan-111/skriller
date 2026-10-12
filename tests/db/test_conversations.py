from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from skriller.db.repositories import ConversationRepository

pytestmark = pytest.mark.integration_db


def test_refinement_preserves_plan_and_messages(database):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "Conversation")
    with database.tenant(actor, workspace["id"]) as session:
        conversation = ConversationRepository.create(session, "Fintech founders")
        message = ConversationRepository.add_message(
            session, conversation["id"], "user", "Find founders"
        )
        first = ConversationRepository.revise_plan(
            session, conversation["id"], {"location": "Bengaluru"}
        )
    with database.tenant(actor, workspace["id"]) as session:
        second = ConversationRepository.revise_plan(
            session, conversation["id"], {"location": "Mumbai"}, parent_id=first["id"]
        )
        assert second["revision"] == 2
        assert second["parent_id"] == first["id"]
        assert ConversationRepository.get_plan(session, first["id"])["interpretation"] == {
            "location": "Bengaluru"
        }
        assert (
            ConversationRepository.add_message(session, conversation["id"], "assistant", "Refined")[
                "sequence"
            ]
            == 2
        )
    for table, record in [("plans", first), ("messages", message)]:
        with (
            pytest.raises(DBAPIError, match="Immutable"),
            database.tenant(actor, workspace["id"]) as session,
        ):
            session.execute(
                sa.text(f"UPDATE {table} SET created_at=now() WHERE id=:id"), {"id": record["id"]}
            )


def test_cross_workspace_conversation_and_parent_rejected(database):
    actor = str(uuid4())
    a, b = database.create_workspace(actor, "A"), database.create_workspace(actor, "B")
    with database.tenant(actor, a["id"]) as session:
        conversation = ConversationRepository.create(session, "A conversation")
        first = ConversationRepository.revise_plan(session, conversation["id"], {"q": "original"})
    with database.tenant(actor, b["id"]) as session:
        assert ConversationRepository.get(session, conversation["id"]) is None
        assert ConversationRepository.get_plan(session, first["id"]) is None
        with pytest.raises(LookupError):
            ConversationRepository.add_message(session, conversation["id"], "user", "cross tenant")
    with database.tenant(actor, a["id"]) as session, pytest.raises(ValueError, match="latest"):
        ConversationRepository.revise_plan(session, conversation["id"], {"q": "stale"})
