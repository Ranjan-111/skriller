"""One copied-node model call; real tenant PG immutable template promotion."""

import json
from dataclasses import replace
from hashlib import sha256
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from test_saved_graph import context_for

from skriller.adaptive import PostgreSQLStorageSystem, StorageScope
from skriller.extraction.adaptive import FieldRule, SemanticAnchor, validate_field
from skriller.extraction.models import LocalStructuredModel
from skriller.extraction.repair import PreservedPage, repair_mapping, rollback_mapping
from skriller.jobs.budget import current_usage
from skriller.jobs.control import cancel

pytestmark = pytest.mark.integration_db
URL = "https://example.org/team"
OLD = '<article><h2>Founder</h2><span class="old">Mira Rao</span></article>'
NEW = '<article><h2>Founder</h2><strong class="renamed">Mira Rao</strong></article>'


class Stub:
    def __init__(self, css, hook=None):
        self.css, self.hook, self.calls = css, hook, 0

    async def ainvoke(self, messages, config):
        self.calls += 1
        if self.hook:
            self.hook()
        return AIMessage(
            content=json.dumps({"css": self.css}),
            usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        )


def setup(database):
    context = context_for(database)
    scope = StorageScope(context.workspace_id, "web", "public", uuid4(), 1)
    rule = FieldRule(
        "founder", ".old", "Mira Rao", "ancestor::article[1]", (SemanticAnchor("h2", "Founder"),)
    )
    assert (
        validate_field(
            OLD, URL, database=database, context=context, storage_scope=scope, rule=rule
        ).status
        == "accepted"
    )
    return context, scope, rule


def store(database, context, scope):
    return PostgreSQLStorageSystem(database, context.actor_id, scope, URL)


async def run(database, context, scope, rule, css, *, current=None, regressions=None, hook=None):
    stub = Stub(css, hook)
    result = await repair_mapping(
        database,
        context,
        scope,
        rule,
        current or PreservedPage.capture(NEW, URL),
        regressions if regressions is not None else (PreservedPage.capture(OLD, URL),),
        model=LocalStructuredModel(model_instance=stub),
        operation_key="repair",
    )
    return result, stub


async def test_changed_dom_promotes_once_and_explicit_rollback_keeps_histories(database):
    context, scope, rule = setup(database)
    before = store(database, context, scope).retrieve(rule.identifier)
    result, stub = await run(database, context, scope, rule, ".renamed")
    assert result.status == "promoted" and result.scope.template_version == 2
    assert stub.calls == 1 and result.rule.css == ".old, .renamed"
    assert store(database, context, scope).retrieve(rule.identifier) == before
    assert store(database, context, result.scope).retrieve(rule.identifier)["tag"] == "strong"
    rolled = rollback_mapping(result)
    assert rolled.scope == scope and rolled.rule == rule
    with database.tenant(context.actor_id, str(context.workspace_id)) as session:
        assert current_usage(session, str(context.job_id))[1]["llm_calls"] == 1


@pytest.mark.parametrize(
    "css,reason",
    [
        ("__import__('os').system('touch hacked')", "mapping_invalid"),
        ("javascript:alert(1)", "mapping_invalid"),
        (".missing", "mapping_missing"),
        ("h2", "field_identity_mismatch"),
    ],
)
async def test_invalid_or_wrong_mapping_never_replaces_baseline(database, css, reason):
    context, scope, rule = setup(database)
    before = store(database, context, scope).retrieve(rule.identifier)
    result, stub = await run(database, context, scope, rule, css)
    assert result.status == "unknown" and result.reason == reason and stub.calls == 1
    assert store(database, context, scope).retrieve(rule.identifier) == before
    assert (
        store(database, context, replace(scope, template_version=2)).retrieve(rule.identifier)
        is None
    )


async def test_wrong_neighbor_regression_prevents_promotion(database):
    context, scope, rule = setup(database)
    bad = '<article><h2>Investor</h2><span class="old">Mira Rao</span></article>'
    result, stub = await run(
        database,
        context,
        scope,
        rule,
        ".renamed",
        regressions=(PreservedPage.capture(OLD, URL), PreservedPage.capture(bad, URL)),
    )
    assert result.reason == "semantic_anchor_mismatch" and stub.calls == 1
    assert (
        store(database, context, replace(scope, template_version=2)).retrieve(rule.identifier)
        is None
    )


@pytest.mark.parametrize("case", ["changed", "other_source", "no_regressions", "oversized"])
async def test_untrusted_source_or_missing_regression_stops_before_model(database, case):
    context, scope, rule = setup(database)
    current = PreservedPage.capture(NEW, URL)
    regressions = (PreservedPage.capture(OLD, URL),)
    if case == "changed":
        current = replace(current, source_sha256=sha256(b"other").hexdigest())
    if case == "other_source":
        regressions = (PreservedPage.capture(OLD, "https://other.org/team"),)
    if case == "no_regressions":
        regressions = ()
    if case == "oversized":
        current = PreservedPage.capture("x" * 2049, URL)
    result, stub = await run(
        database, context, scope, rule, ".renamed", current=current, regressions=regressions
    )
    assert result.status == "unknown" and stub.calls == 0


async def test_cancel_after_model_blocks_promotion(database):
    context, scope, rule = setup(database)

    def hook():
        with database.tenant(context.actor_id, str(context.workspace_id)) as session:
            cancel(session, str(context.job_id))

    result, _ = await run(database, context, scope, rule, ".renamed", hook=hook)
    assert result.status == "unknown"
    assert (
        store(database, context, replace(scope, template_version=2)).retrieve(rule.identifier)
        is None
    )


async def test_existing_next_version_is_not_overwritten(database):
    context, scope, rule = setup(database)
    next_scope = replace(scope, template_version=2)
    validate_field(
        OLD, URL, database=database, context=context, storage_scope=next_scope, rule=rule
    )
    before = store(database, context, next_scope).retrieve(rule.identifier)
    result, _ = await run(database, context, scope, rule, ".renamed")
    assert result.reason == "version_conflict"
    assert store(database, context, next_scope).retrieve(rule.identifier) == before


async def test_regressions_must_include_preserved_baseline_before_model(database):
    context, scope, rule = setup(database)
    result, stub = await run(
        database, context, scope, rule, ".renamed", regressions=(PreservedPage.capture(NEW, URL),)
    )
    assert result.reason == "baseline_regression_required" and stub.calls == 0


async def test_tied_same_name_mapping_is_not_promoted(database):
    context, scope, rule = setup(database)
    duplicate = '<article><h2>Founder</h2><strong class="renamed">Mira Rao</strong><strong class="renamed">Mira Rao</strong></article>'
    result, stub = await run(
        database, context, scope, rule, ".renamed", current=PreservedPage.capture(duplicate, URL)
    )
    assert result.reason == "mapping_ambiguous" and stub.calls == 1
    assert (
        store(database, context, replace(scope, template_version=2)).retrieve(rule.identifier)
        is None
    )
