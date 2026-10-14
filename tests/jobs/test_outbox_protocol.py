import pytest

from skriller.jobs.outbox import CeleryPublisher
from skriller.jobs.worker import create_worker_app


def test_publisher_preserves_current_worker_and_private_task_registry():
    from celery import current_app

    first_database, second_database = object(), object()
    worker = create_worker_app(first_database, "memory://", {})
    worker.set_current()
    publisher = CeleryPublisher("memory://", allow_memory=True)
    assert current_app._get_current_object() is worker
    assert "skriller.jobs.execute_attempt" not in publisher.app.tasks
    other = create_worker_app(second_database, "memory://", {})
    assert worker.tasks["skriller.jobs.execute_attempt"].run.__self__.database is first_database
    assert other.tasks["skriller.jobs.execute_attempt"].run.__self__.database is second_database


def test_memory_transport_requires_opt_in_and_payload_is_id_only():
    with pytest.raises(ValueError, match="opt-in"):
        CeleryPublisher("memory://")
    publisher = CeleryPublisher("memory://", allow_memory=True)
    with pytest.raises(ValueError, match="opaque IDs"):
        publisher.publish(
            "id",
            "execute_job",
            {"job_id": "j", "actor_id": "a", "workspace_id": "w", "token": "secret"},
        )
    with pytest.raises(ValueError, match="topic"):
        publisher.publish("id", "unknown", {})


def test_actual_celery_kombu_memory_protocol_contains_only_ids():
    # Real Celery/Kombu transport integration; not RabbitMQ durability verification.
    publisher = CeleryPublisher("memory://", allow_memory=True)
    with publisher.app.connection_for_read() as connection:
        queue = connection.SimpleQueue("skriller.jobs")
        queue.clear()
        payload = {"workspace_id": "w", "job_id": "j", "actor_id": "a"}
        publisher.publish("stable-message-id", "execute_job", payload)
        message = queue.get(block=False)
        assert message.headers["id"] == "stable-message-id"
        assert message.headers["task"] == "skriller.jobs.execute_job"
        assert message.payload[0] == [payload]
        assert message.payload[1] == {}
        assert message.properties["delivery_mode"] == 2
        message.ack()
        queue.close()
