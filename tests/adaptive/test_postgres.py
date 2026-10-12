from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
import sqlalchemy as sa
from lxml.html import fromstring
from orjson import dumps, loads
from scrapling import Selector
from scrapling.core.utils import _StorageTools

from skriller.adaptive import PostgreSQLStorageSystem, StorageScope
from skriller.db import WorkspaceAccessDenied

pytestmark = pytest.mark.integration_db


def make(
    database,
    actor,
    workspace,
    *,
    template=None,
    version=1,
    access="public",
    source="web",
    url="https://example.com",
):
    return PostgreSQLStorageSystem(
        database=database,
        actor_id=actor,
        scope=StorageScope(
            uuid4() if workspace is None else workspace,
            source,
            access,
            template or uuid4(),
            version,
        ),
        url=url,
    )


def workspace(database, actor):
    from uuid import UUID

    return UUID(database.create_workspace(actor, "Adaptive fixture")["id"])


def test_actual_parser_relocates_with_postgres_storage(database):
    actor = "adaptive-" + uuid4().hex
    scope = StorageScope(workspace(database, actor), "web", "public", uuid4(), 1)
    args = {"database": database, "actor_id": actor, "scope": scope, "url": "https://example.com"}
    old = Selector(
        '<div><article id="target"><h3>Widget</h3><p>Founder</p></article></div>',
        adaptive=True,
        storage=PostgreSQLStorageSystem,
        storage_args=args,
    )
    old.css("#target", identifier="founder", auto_save=True)
    changed = Selector(
        '<section><article data-id="target"><h3>Widget</h3><p>Founder</p></article></section>',
        adaptive=True,
        storage=PostgreSQLStorageSystem,
        storage_args=args,
    )
    relocated = changed.css("#target", identifier="founder", adaptive=True)
    assert relocated and relocated[0].attrib["data-id"] == "target"
    assert relocated[0].css("p")[0].text == "Founder"
    # Sub-selectors reuse the same tenant storage rather than constructor defaults.
    assert old._storage is changed._storage


def test_same_domain_selector_isolated_by_workspace_access_source_template_and_version(database):
    actor_a, actor_b = "adaptive-" + uuid4().hex, "adaptive-" + uuid4().hex
    a, b = workspace(database, actor_a), workspace(database, actor_b)
    template = uuid4()
    original = make(database, actor_a, a, template=template)
    element = fromstring('<article id="target">Tenant A</article>')
    original.save(element, "#target")
    # Match upstream SQLite's JSON round-trip (tuple paths become JSON arrays).
    assert original.retrieve("#target") == loads(dumps(_StorageTools.element_to_dict(element)))
    alternatives = [
        make(database, actor_b, b, template=template),
        make(database, actor_a, a, template=template, access=f"connection:{uuid4()}"),
        make(database, actor_a, a, template=template, source="linkedin"),
        make(database, actor_a, a, template=uuid4()),
        make(database, actor_a, a, template=template, version=2),
        make(database, actor_a, a, template=template, url="https://another-domain.com"),
    ]
    for alternative in alternatives:
        assert alternative.retrieve("#target") is None
        alternative.save(fromstring("<article>Other scoped fingerprint</article>"), "#target")
    assert original.retrieve("#target")["text"] == "Tenant A"
    unauthorized = make(database, actor_b, a, template=template)
    with pytest.raises(WorkspaceAccessDenied):
        unauthorized.retrieve("#target")
    from skriller.db.schema import adaptive_fingerprints

    with database.tenant(actor_b, str(b)) as session:
        # Deliberately bypass the adapter's predicates to verify database RLS.
        assert (
            session.execute(
                sa.select(adaptive_fingerprints.c.id).where(
                    adaptive_fingerprints.c.workspace_id == str(a)
                )
            ).first()
            is None
        )


def test_versions_preserved_and_concurrent_saves_use_independent_transactions(database):
    actor = "adaptive-" + uuid4().hex
    ws, template = workspace(database, actor), uuid4()
    v1 = make(database, actor, ws, template=template)
    v2 = make(database, actor, ws, template=template, version=2)
    v1.save(fromstring("<article>Original version</article>"), "target")
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(
            executor.map(
                lambda index: v2.save(
                    fromstring(f'<article id="item-{index}">Updated {index}</article>'),
                    f"target-{index}",
                ),
                range(12),
            )
        )
    for index in range(12):
        assert v2.retrieve(f"target-{index}")["attributes"]["id"] == f"item-{index}"
    v2.save(fromstring("<article>Updated version</article>"), "target")
    assert v1.retrieve("target")["text"] == "Original version"
    assert v2.retrieve("target")["text"] == "Updated version"


def test_large_unicode_selector_key_and_atomic_same_identifier_update(database):
    actor = "adaptive-" + uuid4().hex
    storage = make(database, actor, workspace(database, actor))
    identifier = "測" * 4096
    storage.save(fromstring("<article>First</article>"), identifier)
    storage.save(fromstring("<article>Updated</article>"), identifier)
    assert storage.retrieve(identifier)["text"] == "Updated"
