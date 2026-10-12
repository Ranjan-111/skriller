from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from skriller.adaptive import PostgreSQLStorageSystem, StorageScope
from skriller.contracts import ExecutionContext
from skriller.extraction.adaptive import FieldRule, SemanticAnchor, validate_field

pytestmark = pytest.mark.integration_db
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "research"


def setup(database):
    actor = "semantic-" + uuid4().hex
    workspace = UUID(database.create_workspace(actor, "Semantic recovery")["id"])
    scope = StorageScope(workspace, "web", "public", uuid4(), 1)
    context = ExecutionContext(
        workspace_id=workspace,
        job_id=uuid4(),
        actor_id=actor,
        plan_revision=1,
        deadline=datetime.now(UTC) + timedelta(minutes=2),
        attempt_budget=5,
    )
    rule = FieldRule(
        "founder.name",
        ".founder-name",
        "Mira Rao",
        "ancestor::article[1]",
        (SemanticAnchor("h2", "Founder"),),
    )
    return scope, context, rule


def check(database, html, scope, context, rule):
    return validate_field(
        html,
        "https://example.com/team",
        database=database,
        context=context,
        storage_scope=scope,
        rule=rule,
    )


def store(database, scope, context):
    return PostgreSQLStorageSystem(database, context.actor_id, scope, "https://example.com/team")


def test_changed_layout_uses_copied_relocation_then_validates_and_versions(database):
    scope, context, rule = setup(database)
    original = (FIXTURES / "company.html").read_text()
    first = check(database, original, scope, context, rule)
    assert first.status == "accepted" and first.template_version == 1
    old = store(database, scope, context).retrieve(rule.identifier)
    changed = (FIXTURES / "changed.html").read_text()
    result = check(database, changed, scope, context, rule)
    assert result.status == "accepted"
    assert result.recovered and result.template_version == 2
    assert result.quote == "Mira Rao" and result.locator.endswith("/strong")
    assert store(database, scope, context).retrieve(rule.identifier) == old
    newer = store(database, replace(scope, template_version=2), context).retrieve(rule.identifier)
    assert newer["tag"] == "strong" and old["tag"] == "span"


@pytest.mark.parametrize(
    "target", ['<span class="founder-name">Mira Rao</span>', "<strong>Mira Rao</strong>"]
)
def test_wrong_neighbor_with_same_person_name_is_quarantined_without_poisoning(database, target):
    scope, context, rule = setup(database)
    assert (
        check(database, (FIXTURES / "company.html").read_text(), scope, context, rule).status
        == "accepted"
    )
    before = store(database, scope, context).retrieve(rule.identifier)
    # A surviving CSS selector is insufficient: the person is in an Investor card.
    bad = f"<article><h2>Investor</h2>{target}<span>Advisor</span></article>"
    result = check(database, bad, scope, context, rule)
    assert result.status == "quarantined" and result.reason == "semantic_anchor_mismatch"
    assert result.quote is None and result.locator is None
    assert store(database, scope, context).retrieve(rule.identifier) == before
    assert (
        store(database, replace(scope, template_version=2), context).retrieve(rule.identifier)
        is None
    )


def test_tied_relocation_is_quarantined_even_when_names_and_roles_match(database):
    scope, context, rule = setup(database)
    original = (
        '<div><article><h2>Founder</h2><span class="founder-name">Mira Rao</span></article></div>'
    )
    assert check(database, original, scope, context, rule).status == "accepted"
    # Two equally valid DOM candidates: no first-match acceptance is permitted.
    changed = "<main><article><h2>Founder</h2><strong>Mira Rao</strong><strong>Mira Rao</strong></article></main>"
    result = check(database, changed, scope, context, rule)
    assert result.status == "quarantined" and result.reason == "mapping_ambiguous"
    assert (
        store(database, replace(scope, template_version=2), context).retrieve(rule.identifier)
        is None
    )


def test_wrong_target_text_and_cross_container_anchor_are_rejected(database):
    scope, context, rule = setup(database)
    wrong = '<article><h2>Founder</h2><span class="founder-name">Other Person</span></article>'
    assert check(database, wrong, scope, context, rule).reason == "field_identity_mismatch"
    unrelated = '<article><h2>Founder</h2></article><article><span class="founder-name">Mira Rao</span></article>'
    assert check(database, unrelated, scope, context, rule).reason == "semantic_anchor_mismatch"
    assert store(database, scope, context).retrieve(rule.identifier) is None


def test_context_scope_and_connection_are_checked_before_parser_io(database):
    from skriller.db import WorkspaceAccessDenied

    scope, context, rule = setup(database)
    with pytest.raises(WorkspaceAccessDenied):
        check(database, "<p>Data</p>", replace(scope, workspace_id=uuid4()), context, rule)
    with pytest.raises(WorkspaceAccessDenied):
        check(
            database,
            "<p>Data</p>",
            replace(scope, access_scope=f"connection:{uuid4()}"),
            context,
            rule,
        )


def test_bounded_input_and_template_rules(database):
    scope, context, rule = setup(database)
    assert (
        check(database, "x" * (2 * 1024 * 1024 + 1), scope, context, rule).reason
        == "input_budget_exhausted"
    )
    assert (
        check(database, "<main>" + "<b>x</b>" * 20001 + "</main>", scope, context, rule).reason
        == "element_budget_exhausted"
    )
    with pytest.raises(ValueError):
        replace(rule, container_xpath="//body")
    with pytest.raises(ValueError):
        replace(rule, minimum_similarity=20)
    with pytest.raises(ValueError):
        replace(rule, anchors=())
