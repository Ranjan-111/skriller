"""Operator-reviewed, exact-source templates over saved public page bytes.

The server config is never populated from a prompt, model output or page. Runtime
reads reuse approved fingerprints but do not learn/publish candidate templates.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from agent_reach.utils.url import normalize_public_http_url
from cssselect import SelectorError
from lxml.etree import XPathError
from pydantic import BaseModel, ConfigDict, Field, field_validator

from skriller.adaptive import StorageScope
from skriller.extraction.adaptive import FieldRule, SemanticAnchor, validate_field
from skriller.extraction.presets import DirectoryClaim


class Anchor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    css: str = Field(min_length=1, max_length=1000)
    expected_text: str = Field(min_length=1, max_length=500)


class ReviewedField(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    field: Literal["company_name", "description", "headquarters", "industry", "service_name"]
    identifier: str = Field(min_length=1, max_length=200)
    css: str = Field(min_length=1, max_length=1000)
    expected_text: str = Field(min_length=1, max_length=500)
    container_xpath: str = Field(min_length=1, max_length=100)
    anchors: list[Anchor] = Field(min_length=1, max_length=10)

    def rule(self):
        return FieldRule(
            self.identifier,
            self.css,
            self.expected_text,
            self.container_xpath,
            tuple(SemanticAnchor(item.css, item.expected_text) for item in self.anchors),
        )


class ReviewedTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    workspace_id: UUID
    source_url: str = Field(min_length=1, max_length=4096)
    template_id: UUID
    template_version: int = Field(ge=1, le=1_000_000)
    fields: list[ReviewedField] = Field(min_length=1, max_length=20)

    @field_validator("source_url")
    @classmethod
    def public_url(cls, value):
        return normalize_public_http_url(value)


class Registry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    templates: list[ReviewedTemplate] = Field(max_length=100)


def template_observations(database, context, html, source_url, configuration):
    """Return source observations, never named-subject acceptance or fit proof."""
    if context.connection_ref is not None:
        return (), [{"status": "quarantined", "reason": "template_access_scope_mismatch"}]
    try:
        from skriller.research.template_registry import selected_templates

        source_url = normalize_public_http_url(source_url)
        with database.tenant(context.actor_id, str(context.workspace_id)) as session:
            active = selected_templates(session)
        selected = [template for template in active if template.source_url == source_url]
        if configuration:
            with Path(configuration).open("rb") as stream:
                raw = stream.read(1_048_577)
            if len(raw) > 1_048_576:
                raise ValueError("Template registry exceeds bounds")
            registry = Registry.model_validate_json(raw)
            active_ids = {template.template_id for template in active}
            selected.extend(
                template
                for template in registry.templates
                if template.workspace_id == context.workspace_id
                and template.source_url == source_url
                and template.template_id not in active_ids
            )
        fields = [item.field for template in selected for item in template.fields]
        if len(fields) != len(set(fields)) or len(fields) > 20:
            raise ValueError("Ambiguous template field registration")
        # Validate every server rule before invoking the copied selector.
        rules = [(template, item, item.rule()) for template in selected for item in template.fields]
    except (OSError, ValueError):
        return (), [{"status": "quarantined", "reason": "template_configuration_invalid"}]
    observations: list[DirectoryClaim] = []
    diagnostics: list[dict[str, str | bool | int | None]] = []
    for template, item, rule in rules:
        if datetime.now(UTC) >= context.deadline:
            diagnostics.append({"status": "quarantined", "reason": "deadline_exceeded"})
            break
        try:
            result = validate_field(
                html,
                source_url,
                database=database,
                context=context,
                storage_scope=StorageScope(
                    context.workspace_id,
                    "web",
                    "public",
                    template.template_id,
                    template.template_version,
                ),
                rule=rule,
                learn=False,
            )
        except (ValueError, SelectorError, XPathError):
            diagnostics.append(
                {
                    "field": item.field,
                    "status": "quarantined",
                    "reason": "template_selector_invalid",
                }
            )
            continue
        diagnostics.append(
            {
                "field": item.field,
                "status": result.status,
                "reason": result.reason,
                "recovered": result.recovered,
                "template_version": result.template_version,
            }
        )
        if result.status == "accepted" and result.quote:
            observations.append(
                DirectoryClaim(
                    field=item.field,
                    value=result.quote,
                    quote=result.quote,
                    evidence_ids=(),
                    source_url=source_url,
                    source_sha256=result.source_sha256,
                    observed_at=datetime.now(UTC),
                )
            )
    return tuple(observations), diagnostics
