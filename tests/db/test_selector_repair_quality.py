"""Opt-in local proposal quality through copied graph and preserved-page validation."""

import os

import pytest
from test_selector_repair import NEW, OLD, URL, setup, store

from skriller.extraction.models import LocalStructuredModel
from skriller.extraction.repair import PreservedPage, repair_mapping, rollback_mapping

pytestmark = [
    pytest.mark.integration_db,
    pytest.mark.skipif(
        os.environ.get("SKRILLER_RUN_LOCAL_MODEL_TESTS") != "1",
        reason="Explicit opt-in required for bounded local repair proposal",
    ),
]


@pytest.mark.parametrize("wrong_neighbor", [False, True])
async def test_local_repair_retains_literal_identity_and_regression_semantics(
    database, wrong_neighbor
):
    context, scope, rule = setup(database)
    before = store(database, context, scope).retrieve(rule.identifier)
    regressions = [PreservedPage.capture(OLD, URL)]
    if wrong_neighbor:
        regressions.append(PreservedPage.capture(OLD.replace("Founder", "Investor"), URL))
    model = LocalStructuredModel()
    result = await repair_mapping(
        database,
        context,
        scope,
        rule,
        PreservedPage.capture(NEW, URL),
        tuple(regressions),
        model=model,
        operation_key="local-repair-quality",
    )
    assert store(database, context, scope).retrieve(rule.identifier) == before
    if wrong_neighbor:
        assert result.status == "unknown" and result.reason == "semantic_anchor_mismatch"
        assert result.scope == scope
    else:
        assert result.status == "promoted" and result.scope.template_version == 2
        assert store(database, context, result.scope).retrieve(rule.identifier)["tag"] == "strong"
        rolled = rollback_mapping(result)
        assert rolled.scope == scope and rolled.rule == rule
