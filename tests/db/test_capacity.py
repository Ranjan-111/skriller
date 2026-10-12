from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from time import sleep
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from test_budget import job_fixture

from skriller.db import Database
from skriller.jobs.capacity import CapacityUnavailable, acquire, release

pytestmark = pytest.mark.integration_db


def names():
    key = str(uuid4())
    return f"s-{key}", f"h-{key}.example"


def test_two_workers_share_source_and_host_limits(database):
    actor, workspace, job = job_fixture(database)
    db = Database(database.engine.url, pool_size=2)
    source, host = names()

    def worker(index):
        try:
            with db.tenant(actor, workspace) as session:
                return acquire(session, job, kind="http", source=source, host=f"{index}.{host}")
        except CapacityUnavailable:
            return None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            leases = list(pool.map(worker, range(2)))
        assert sum(lease is not None for lease in leases) == 1
        with db.tenant(actor, workspace) as session:
            lease = next(lease for lease in leases if lease is not None)
            release(session, lease)
            first = acquire(session, job, kind="http", source=source, host=host)
            with pytest.raises(CapacityUnavailable):
                acquire(session, job, kind="browser", source=source + "other", host=host)
            release(session, first)
    finally:
        db.dispose()


@pytest.mark.parametrize("kind,cap", [("http", 8), ("browser", 2), ("model", 1)])
def test_global_caps_apply_across_workspaces(database, kind, cap):
    fixtures = [job_fixture(database) for _ in range(cap + 1)]
    leases = []
    try:
        for actor, workspace, job in fixtures[:cap]:
            source, host = names()
            with database.tenant(actor, workspace) as session:
                leases.append(
                    (actor, workspace, acquire(session, job, kind=kind, source=source, host=host))
                )
        actor, workspace, job = fixtures[-1]
        with database.tenant(actor, workspace) as session:
            source, host = names()
            with pytest.raises(CapacityUnavailable):
                acquire(session, job, kind=kind, source=source, host=host)
    finally:
        for actor, workspace, lease in leases:
            with database.tenant(actor, workspace) as session:
                assert release(session, lease)


@pytest.mark.parametrize("header", ["120", "date", "nan"])
def test_retry_after_and_adaptive_backoff_persist_across_processes(database, header):
    actor, workspace, job = job_fixture(database)
    source, host = names()
    if header == "date":
        header = format_datetime(datetime.now(UTC) + timedelta(seconds=120), usegmt=True)
    with database.tenant(actor, workspace) as session:
        lease = acquire(session, job, kind="http", source=source, host=host)
        assert release(session, lease, latency=0.01, ok=False, headers={"Retry-After": header})
    # A separate interpreter proves cadence is not an in-memory throttle cache.
    import subprocess
    import sys

    probe = """
import sys
from skriller.settings import Settings
from skriller.db import Database
from skriller.jobs.capacity import acquire, release, CapacityUnavailable
actor, workspace, job, source, host = sys.argv[1:]
db = Database(Settings().application_database_url)
try:
    with db.tenant(actor, workspace) as session:
        try:
            lease = acquire(session, job, kind="http", source=source, host=host)
        except CapacityUnavailable:
            status = 0
        else:
            release(session, lease)
            status = 2
finally:
    db.dispose()
sys.exit(status)
"""
    result = subprocess.run(
        [sys.executable, "-c", probe, actor, workspace, job, source, host],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_crashed_worker_expiry_recovers_and_stale_release_is_fenced(database):
    actor, workspace, job = job_fixture(database)
    source, host = names()
    with database.tenant(actor, workspace) as session:
        old = acquire(session, job, kind="http", source=source, host=host, ttl_seconds=1)
    sleep(1.1)
    with database.tenant(actor, workspace) as session:
        successor = acquire(session, job, kind="http", source=source, host=host)
        assert not release(session, old, latency=1, ok=False, headers={"Retry-After": "120"})
        with pytest.raises(CapacityUnavailable):
            acquire(session, job, kind="http", source=source, host=host)
        assert release(session, successor)


def test_tenant_cannot_release_other_lease_or_read_global_state(database):
    actor, workspace, job = job_fixture(database)
    actor2, workspace2, _job2 = job_fixture(database)
    source, host = names()
    with database.tenant(actor, workspace) as session:
        lease = acquire(session, job, kind="http", source=source, host=host)
    with database.tenant(actor2, workspace2) as session:
        assert not release(session, lease)
    with pytest.raises(DBAPIError), database.tenant(actor2, workspace2) as session:
        session.execute(sa.text("SELECT * FROM capacity_leases"))
    with pytest.raises(DBAPIError), database.tenant(actor2, workspace2) as session:
        acquire(session, job, kind="http", source=source + "2", host=host + "2")
    with database.tenant(actor, workspace) as session:
        assert release(session, lease)


def test_worker_capacity_denial_does_not_start_io_or_reserve_budget(database):
    from dataclasses import replace
    from threading import Event

    from test_worker import context, handler

    from skriller.jobs.budget import current_usage
    from skriller.jobs.worker import CheckpointWorker

    first, second = context(database), context(database)
    source, host = names()
    started, finish = Event(), Event()
    db = Database(database.engine.url, pool_size=2)

    def bounded_run(_plan, timeout):
        assert 0 < timeout <= 120
        started.set()
        assert finish.wait(timeout=5)
        return "Capacity bounded", 0, {"llm_calls": 1, "tokens": 2}

    bounded = replace(
        handler(lambda _: None),
        run_with_deadline=bounded_run,
        capacity_kind="http",
        capacity_source=source,
        capacity_host=host,
    )
    worker = CheckpointWorker(db, {"discovering": bounded})
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            active = pool.submit(worker.execute, first)
            assert started.wait(timeout=5)
            assert worker.execute(second) == {"status": "capacity_exhausted"}
            with db.tenant(second["actor_id"], second["workspace_id"]) as session:
                assert current_usage(session, second["job_id"])[1]["llm_calls"] == 0
            finish.set()
            assert active.result(timeout=5)["status"] == "checkpointed"
        # Different source/host can proceed: the first slot was released.
        with db.tenant(second["actor_id"], second["workspace_id"]) as session:
            lease = acquire(
                session, second["job_id"], kind="http", source=source + "other", host=host + "other"
            )
            assert release(session, lease)
    finally:
        finish.set()
        db.dispose()


def test_workspace_limit_counts_distinct_jobs(database):
    from skriller.contracts import SearchPlan
    from skriller.db import ConversationRepository, JobRepository

    actor, workspace, first = job_fixture(database)
    jobs = [first]
    with database.tenant(actor, workspace) as session:
        for _ in range(2):
            conversation = ConversationRepository.create(session, "Capacity queued")
            plan = SearchPlan(
                workspace_id=workspace,
                conversation_id=conversation["id"],
                revision=1,
                entity_type="company",
            )
            revision = ConversationRepository.revise_plan(
                session, conversation["id"], plan.model_dump(mode="json")
            )
            job = JobRepository.create(session, conversation["id"], revision["id"], str(uuid4()))
            JobRepository.transition(session, job["id"], "queued")
            jobs.append(job["id"])
    held = []
    try:
        for job in jobs[:2]:
            source, host = names()
            with database.tenant(actor, workspace) as session:
                held.append(acquire(session, job, kind="http", source=source, host=host))
        source, host = names()
        with database.tenant(actor, workspace) as session:
            with pytest.raises(CapacityUnavailable):
                acquire(session, jobs[2], kind="http", source=source, host=host)
            assert release(session, held.pop())
            held.append(acquire(session, jobs[2], kind="http", source=source, host=host))
    finally:
        with database.tenant(actor, workspace) as session:
            for lease in held:
                assert release(session, lease)


def test_worker_persists_typed_retry_after_without_raw_provider_error(database):
    from dataclasses import replace

    from test_worker import context, handler

    from skriller.connectors.search import SearchUnavailable
    from skriller.contracts import Failure
    from skriller.jobs.worker import CheckpointWorker

    payload = context(database)
    source, host = names()

    def blocked(_plan, _timeout):
        raise SearchUnavailable(
            Failure(code="rate_limited", message="Redacted", retry_after_seconds=120)
        )

    bounded = replace(
        handler(lambda _: None),
        run_with_deadline=blocked,
        capacity_kind="http",
        capacity_source=source,
        capacity_host=host,
    )
    worker = CheckpointWorker(database, {"discovering": bounded})
    assert worker.execute(payload) == {"status": "source_unavailable"}
    actor, workspace, job = job_fixture(database)
    with database.tenant(actor, workspace) as session, pytest.raises(CapacityUnavailable):
        acquire(session, job, kind="http", source=source, host=host)
