"""PostgreSQL transport for copied Scrapling fingerprints and storage contract.

Fingerprint construction, base-domain handling, parser relocation and selector
matching are reused from attributed copied Scrapling code without modifications.
Only the persistence transport and product namespace are adapted here.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, get_args
from urllib.parse import urlsplit
from uuid import UUID

import sqlalchemy as sa
from agent_reach.utils.url import normalize_public_http_url
from lxml.html import HtmlElement
from scrapling.core.storage import StorageSystemMixin
from scrapling.core.utils import _StorageTools
from sqlalchemy.dialects.postgresql import insert

from skriller.contracts import ExecutionContext, Source
from skriller.db import Database, WorkspaceAccessDenied


@dataclass(frozen=True)
class StorageScope:
    workspace_id: UUID
    source: Source
    access_scope: str
    template_id: UUID
    template_version: int

    def __post_init__(self):
        if not isinstance(self.workspace_id, UUID) or not isinstance(self.template_id, UUID):
            raise TypeError("Storage scope requires validated workspace and template UUIDs")
        if self.source not in get_args(Source):
            raise ValueError("Unsupported fingerprint source")
        if (
            isinstance(self.template_version, bool)
            or not isinstance(self.template_version, int)
            or self.template_version < 1
        ):
            raise ValueError("Template version must be a positive integer")
        if self.access_scope != "public":
            if not self.access_scope.startswith("connection:"):
                raise ValueError("Access scope must be public or an explicit connection UUID")
            try:
                connection = UUID(self.access_scope.removeprefix("connection:"))
            except ValueError as exc:
                raise ValueError("Access scope must contain a valid connection UUID") from exc
            if self.access_scope != f"connection:{connection}":
                raise ValueError("Connection scope must be canonical")


def storage_arguments(
    database: Database, context: ExecutionContext, scope: StorageScope, url: str
) -> dict[str, Any]:
    """Build hashable parser constructor args from trusted execution context."""
    if context.workspace_id != scope.workspace_id:
        raise WorkspaceAccessDenied("Fingerprint scope differs from execution workspace")
    expected_access = (
        f"connection:{context.connection_ref}" if context.connection_ref is not None else "public"
    )
    if scope.access_scope != expected_access:
        raise WorkspaceAccessDenied("Fingerprint connection differs from execution context")
    return {"database": database, "actor_id": context.actor_id, "scope": scope, "url": url}


@lru_cache(maxsize=64, typed=True)
class PostgreSQLStorageSystem(StorageSystemMixin):
    """Cached constructor required by Scrapling; no cached sessions or connections.

    Each operation gets an independently membership-checked, non-owner PostgreSQL
    tenant transaction. Database RLS and namespace predicates enforce isolation.
    Cache keys include every namespace field, actor, database identity and URL.
    """

    def __init__(self, database: Database, actor_id: str, scope: StorageScope, url: str):
        if not actor_id or len(actor_id) > 128:
            raise WorkspaceAccessDenied("Fingerprint storage needs verified actor identity")
        url = normalize_public_http_url(url)
        super().__init__(url)
        self.database = database
        self.actor_id = actor_id
        self.scope = scope
        # Reuse upstream domain extraction. Unknown public suffixes must not all
        # share its generic 'default' key, so preserve their validated hostname.
        domain = self._get_base_url()
        self.domain = urlsplit(url).hostname if domain == "default" else domain
        if not self.domain or len(self.domain) > 253:
            raise ValueError("Fingerprint domain is missing or too long")

    def _key(self, identifier: str) -> dict[str, Any]:
        if not isinstance(identifier, str) or not identifier or len(identifier) > 4096:
            raise ValueError("Fingerprint identifier must contain 1–4096 characters")
        return {
            "workspace_id": str(self.scope.workspace_id),
            "source": self.scope.source,
            "access_scope": self.scope.access_scope,
            "domain": self.domain,
            "template_id": str(self.scope.template_id),
            "template_version": self.scope.template_version,
            "selector_identifier": identifier,
        }

    def save(self, element: HtmlElement, identifier: str) -> None:
        from skriller.db.schema import adaptive_fingerprints

        key = self._key(identifier)
        # Exact copied algorithm used by SQLiteStorageSystem.save; do not rebuild
        # element attributes, parent/sibling/children or path fingerprints.
        element_data = _StorageTools.element_to_dict(element)
        statement = insert(adaptive_fingerprints).values(**key, element_data=element_data)
        upsert = statement.on_conflict_do_update(
            # The database computes a bounded hash to keep large identifiers out
            # of the btree key. Equality on the original identifier makes hash
            # collisions fail closed instead of replacing another fingerprint.
            constraint="adaptive_namespace",
            set_={"element_data": statement.excluded.element_data},
            where=adaptive_fingerprints.c.selector_identifier
            == statement.excluded.selector_identifier,
        ).returning(adaptive_fingerprints.c.id)
        with self.database.tenant(self.actor_id, str(self.scope.workspace_id)) as session:
            if session.execute(upsert).scalar_one_or_none() is None:
                raise ValueError("Fingerprint identifier hash collision; original record preserved")

    def retrieve(self, identifier: str) -> dict[str, Any] | None:
        from skriller.db.schema import adaptive_fingerprints

        key = self._key(identifier)
        statement = sa.select(adaptive_fingerprints.c.element_data).where(
            *(adaptive_fingerprints.c[name] == value for name, value in key.items())
        )
        with self.database.tenant(self.actor_id, str(self.scope.workspace_id)) as session:
            return session.execute(statement).scalar_one_or_none()

    def close(self) -> None:
        """No retained connection; shared Database lifecycle belongs to its owner."""
