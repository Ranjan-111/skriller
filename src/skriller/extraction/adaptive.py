"""Semantic validation around copied Scrapling relocation; no matching engine rewrite.

Rules are trusted connector templates, never instructions taken from page content.
A structural match is only a candidate until identity and same-container field
relationships pass. Rejected/ambiguous candidates never update fingerprints.
"""

import re
from dataclasses import dataclass, replace
from hashlib import sha256

from scrapling import Selector

from skriller.adaptive import PostgreSQLStorageSystem, StorageScope, storage_arguments
from skriller.contracts import ExecutionContext
from skriller.db import Database


@dataclass(frozen=True)
class SemanticAnchor:
    css: str
    expected_text: str

    def __post_init__(self):
        if (
            not self.css
            or len(self.css) > 1000
            or not self.expected_text.strip()
            or len(self.expected_text) > 500
        ):
            raise ValueError("Bounded semantic anchor required")


@dataclass(frozen=True)
class FieldRule:
    identifier: str
    css: str
    expected_text: str
    container_xpath: str
    anchors: tuple[SemanticAnchor, ...]
    minimum_similarity: int = 40

    def __post_init__(self):
        if (
            not self.identifier
            or len(self.identifier) > 200
            or not self.css
            or len(self.css) > 1000
        ):
            raise ValueError("Bounded field identity and selector required")
        if not self.expected_text.strip() or len(self.expected_text) > 500:
            raise ValueError("Known field identity is required before adaptive acceptance")
        if not re.fullmatch(r"ancestor::[a-z][a-z0-9]*\[1\]", self.container_xpath):
            raise ValueError("Field relationship must use the nearest explicit ancestor container")
        if not 1 <= len(self.anchors) <= 10 or not all(
            isinstance(a, SemanticAnchor) for a in self.anchors
        ):
            raise ValueError("At least one typed relationship anchor is required")
        if (
            isinstance(self.minimum_similarity, bool)
            or not isinstance(self.minimum_similarity, int)
            or not 40 <= self.minimum_similarity <= 100
        ):
            raise ValueError("Similarity cannot weaken the copied default threshold")


@dataclass(frozen=True)
class ValidatedField:
    status: str
    reason: str
    source_sha256: str
    recovered: bool = False
    quote: str | None = None
    locator: str | None = None
    template_version: int | None = None


def _normalized(value: str) -> str:
    return " ".join(value.split()).casefold()


def validate_field(
    html: str,
    source_url: str,
    *,
    database: Database,
    context: ExecutionContext,
    storage_scope: StorageScope,
    rule: FieldRule,
) -> ValidatedField:
    """Read an already-collected page; quarantine uncertain mappings.

    The copied selector performs all CSS/XPath matching and similarity relocation.
    Version1 is learned only after semantic validation; a recovered candidate is
    saved in the next explicit namespace version, preserving the previous record.
    This validates a known identity/relationship, not a newly inferred person.
    """
    raw = html.encode("utf-8")
    digest = sha256(raw).hexdigest()
    if len(raw) > 2 * 1024 * 1024:
        return ValidatedField("quarantined", "input_budget_exhausted", digest)
    args = storage_arguments(database, context, storage_scope, source_url)
    document = Selector(
        html or "<html><body></body></html>",
        adaptive=True,
        storage=PostgreSQLStorageSystem,
        storage_args=args,
    )
    if len(document.xpath("//*")) > 20000:
        return ValidatedField("quarantined", "element_budget_exhausted", digest)
    # No automatic save: a wrong direct match must not poison trusted history.
    direct = document.css(rule.css, auto_save=False)
    recovered = not bool(direct)
    candidates = direct or document.css(
        rule.css,
        identifier=rule.identifier,
        adaptive=True,
        auto_save=False,
        percentage=rule.minimum_similarity,
    )
    if not candidates:
        return ValidatedField("quarantined", "mapping_missing", digest, recovered)
    if len(candidates) != 1:
        return ValidatedField("quarantined", "mapping_ambiguous", digest, recovered)
    candidate = candidates[0]
    quote = str(candidate.get_all_text(separator=" ", strip=True))
    if len(quote) > 4096:
        return ValidatedField("quarantined", "evidence_budget_exhausted", digest, recovered)
    if _normalized(quote) != _normalized(rule.expected_text):
        return ValidatedField("quarantined", "field_identity_mismatch", digest, recovered)
    containers = candidate.xpath(rule.container_xpath)
    if len(containers) != 1:
        return ValidatedField("quarantined", "field_relationship_missing", digest, recovered)
    for anchor in rule.anchors:
        matches = containers[0].css(anchor.css)
        if len(matches) != 1 or _normalized(
            str(matches[0].get_all_text(separator=" ", strip=True))
        ) != _normalized(anchor.expected_text):
            return ValidatedField("quarantined", "semantic_anchor_mismatch", digest, recovered)
    version = storage_scope.template_version + int(recovered)
    destination = PostgreSQLStorageSystem(
        **{**args, "scope": replace(storage_scope, template_version=version)}
    )
    # Selector.save accepts the element root; its same copied storage algorithm
    # is used without altering similarity scores or rebuilding fingerprints.
    destination.save(candidate._root, rule.identifier)
    return ValidatedField(
        "accepted",
        "validated_recovery" if recovered else "validated_direct",
        digest,
        recovered,
        quote,
        candidate.generate_full_xpath_selector,
        version,
    )
