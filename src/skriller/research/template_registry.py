"""Owner-reviewed immutable templates with serialized active selection and audit."""

from hashlib import sha256
from uuid import UUID

import sqlalchemy as sa
from cssselect import SelectorError
from lxml.cssselect import CSSSelector
from sqlalchemy.dialects.postgresql import insert

from skriller.db.repositories import require_owner, scope
from skriller.db.schema import active_page_templates as active
from skriller.db.schema import page_template_audit as audit
from skriller.db.schema import reviewed_template_versions as versions
from skriller.research.adaptive_templates import ReviewedTemplate


def selected_templates(session, source_url=None):
    query = (
        sa.select(versions, active.c.id.label("active_template_id"))
        .join(
            active,
            sa.and_(
                active.c.workspace_id == versions.c.workspace_id,
                active.c.version_id == versions.c.id,
            ),
        )
        .where(versions.c.workspace_id == scope(session))
    )
    if source_url is not None:
        query = query.where(
            versions.c.source_hash == sha256(source_url.encode()).hexdigest(),
            versions.c.source_url == source_url,
        )
    rows = session.execute(query.order_by(versions.c.template_id).limit(101)).mappings().all()
    if len(rows) > 100:
        raise ValueError("Active template registry exceeds bounds")
    result = []
    for row in rows:
        template = ReviewedTemplate.model_validate(row["payload"])
        if (
            str(template.workspace_id) != scope(session)
            or str(template.template_id) != row["active_template_id"]
            or str(template.template_id) != row["template_id"]
            or template.template_version != row["template_version"]
            or template.source_url != row["source_url"]
        ):
            raise ValueError("Stored template scope mismatch")
        result.append(template)
    return result


def _lock(session):
    require_owner(session)
    session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": "reviewed-template-registry:" + scope(session)},
    )


def _validate(template):
    fields = [item.field for item in template.fields]
    identifiers = [item.identifier for item in template.fields]
    if len(set(fields)) != len(fields) or len(set(identifiers)) != len(identifiers):
        raise ValueError("Reviewed template fields and identifiers must be unique")
    try:
        for field in template.fields:
            field.rule()
            CSSSelector(field.css)
            for anchor in field.anchors:
                CSSSelector(anchor.css)
    except SelectorError:
        raise ValueError("Reviewed template contains invalid selectors") from None


def _select(session, template, version_id, expected_version, action):
    selected = selected_templates(session)
    current = next((item for item in selected if item.template_id == template.template_id), None)
    if (current.template_version if current else None) != expected_version:
        raise ValueError("Active template changed; refresh its expected version")
    if current and current.source_url != template.source_url:
        raise ValueError("Template source cannot change across versions")
    others = [item for item in selected if item.template_id != template.template_id]
    if len(others) >= 100:
        raise ValueError("Active template registry exceeds bounds")
    fields = {
        field.field
        for item in others
        if item.source_url == template.source_url
        for field in item.fields
    }
    if fields.intersection(field.field for field in template.fields):
        raise ValueError("Active source field already has a reviewed mapping")
    if len(fields) + len(template.fields) > 20:
        raise ValueError("Active source field count exceeds bounds")
    statement = insert(active).values(
        workspace_id=scope(session),
        id=str(template.template_id),
        version_id=version_id,
        updated_by=session.info["actor_id"],
    )
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["workspace_id", "id"],
            set_={
                "version_id": version_id,
                "updated_by": session.info["actor_id"],
            },
        )
    )
    session.execute(
        sa.insert(audit).values(
            workspace_id=scope(session),
            template_id=str(template.template_id),
            previous_version=expected_version,
            selected_version=template.template_version,
            action=action,
            created_by=session.info["actor_id"],
        )
    )
    return template


def publish_template(session, template: ReviewedTemplate, *, expected_version: int | None):
    with session.begin_nested():
        return _publish_template(session, template, expected_version=expected_version)


def _publish_template(session, template: ReviewedTemplate, *, expected_version: int | None):
    _lock(session)
    if str(template.workspace_id) != scope(session):
        raise ValueError("Reviewed template belongs to another workspace")
    _validate(template)
    latest = (
        session.execute(
            sa.select(versions.c.template_version, versions.c.source_url)
            .where(
                versions.c.workspace_id == scope(session),
                versions.c.template_id == str(template.template_id),
            )
            .order_by(versions.c.template_version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if latest is not None and latest["source_url"] != template.source_url:
        raise ValueError("Template source cannot change across versions")
    if template.template_version != (latest["template_version"] if latest else 0) + 1:
        raise ValueError("Publish requires the next immutable version")
    identifier = session.execute(
        sa.insert(versions)
        .values(
            workspace_id=scope(session),
            template_id=str(template.template_id),
            template_version=template.template_version,
            source_url=template.source_url,
            source_hash=sha256(template.source_url.encode()).hexdigest(),
            payload=template.model_dump(mode="json"),
            created_by=session.info["actor_id"],
        )
        .returning(versions.c.id)
    ).scalar_one()
    return _select(session, template, identifier, expected_version, "publish")


def rollback_template(session, template_id: UUID, *, target_version: int, expected_version: int):
    if not 1 <= target_version < expected_version:
        raise ValueError("Rollback requires an earlier version")
    _lock(session)
    row = (
        session.execute(
            sa.select(versions).where(
                versions.c.workspace_id == scope(session),
                versions.c.template_id == str(template_id),
                versions.c.template_version == target_version,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise LookupError("Reviewed template version unavailable")
    template = ReviewedTemplate.model_validate(row["payload"])
    _validate(template)
    return _select(session, template, row["id"], expected_version, "rollback")
