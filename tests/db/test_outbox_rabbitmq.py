"""Actual local RabbitMQ protocol gate; no memory transport fallback."""

from uuid import uuid4

import pytest

from skriller.contracts import SearchPlan
from skriller.db import ConversationRepository
from skriller.jobs.outbox import CeleryPublisher, DispatchScope, OutboxDispatcher, submit
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db


def test_real_rabbitmq_confirms_id_only_persistent_publication(database):
    actor = str(uuid4())
    workspace = database.create_workspace(actor, "Real queue")["id"]
    with database.tenant(actor, workspace) as session:
        conversation = ConversationRepository.create(session, "Confirmed dispatch")
        plan = SearchPlan(
            workspace_id=workspace,
            conversation_id=conversation["id"],
            revision=1,
            entity_type="company",
        )
        revision = ConversationRepository.revise_plan(
            session, conversation["id"], plan.model_dump(mode="json")
        )
        job = submit(session, conversation["id"], revision["id"], str(uuid4()))
    publisher = CeleryPublisher(Settings().broker_url)
    assert publisher.app.conf.broker_transport_options["confirm_publish"]
    message_id = OutboxDispatcher(database, publisher).dispatch_one(DispatchScope(actor, workspace))
    with publisher.app.connection_for_read() as connection:
        queue = connection.SimpleQueue("skriller.jobs")
        message = queue.get(block=True, timeout=5)
        try:
            assert message.headers["id"] == message_id
            assert message.properties["delivery_mode"] == 2
            assert message.payload[0] == [
                {"workspace_id": workspace, "job_id": job["id"], "actor_id": actor}
            ]
        finally:
            message.ack()
            queue.close()
    assert (
        OutboxDispatcher(database, publisher).dispatch_one(DispatchScope(actor, workspace)) is None
    )
