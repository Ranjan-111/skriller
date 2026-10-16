"""Labelled eligibility/identity checks through actual tenant database services.

Fixtures seed reviewed facts, so this measures downstream decisions, never live
source access, model extraction, representative pilot quality or review effort.
"""

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from skriller.contracts import Criterion, SearchPlan
from skriller.db import ResearchRepository
from skriller.db.schema import claims
from skriller.qualification.identity import compare
from skriller.qualification.service import qualify_entity

pytestmark = pytest.mark.integration_db
CORPUS = Path(__file__).parents[1] / "fixtures/research/semantic-quality.json"


def _criteria(case, name):
    return [
        Criterion(field=field, operator=operator, value=value)
        for field, operator, value in case.get(name, [])
    ]


def _seed_fact(session, entity_id, field, value, case):
    now = datetime.now(UTC)
    record = ResearchRepository.add_evidence(
        session,
        source_url="https://example.org/synthetic-quality",
        source_platform="web",
        collected_at=now - timedelta(days=case.get("age_days", 0)),
        expires_at=now - timedelta(seconds=1) if case.get("expired") else None,
        excerpt=str(value),
    )
    claim = ResearchRepository.claim(
        session,
        entity_id,
        field,
        value,
        mode="observed",
        status=case.get("claim_status", "accepted"),
        evidence_ids=[record["id"]],
    )
    # These are separately reviewed fixture facts, including explicit conflicts.
    # Preserve both conflicting accepted facts for the comparison to evaluate.
    if case.get("claim_status", "accepted") == "accepted":
        session.execute(
            sa.update(claims).where(claims.c.entity_id == entity_id).values(status="accepted")
        )
    return claim


def _report(dimension, corpus, rows, tmp_path):
    correct = sum(row["exact_label_correct"] for row in rows)
    predicted_positive = sum(row["outcome"] == "accepted" for row in rows)
    true_positive = sum(
        row["outcome"] == "accepted" and row["expected"] == "accept" for row in rows
    )
    report = {
        "schema_version": 1,
        "dimension": dimension,
        "source_group": "synthetic_fixture",
        "model_mode": "actual_local_database_no_model",
        "scope": corpus["scope"],
        "evaluation_scope": "Development fixture acceptance over seeded reviewed facts; no live platform or model execution",
        "corpus_sha256": hashlib.sha256(CORPUS.read_bytes()).hexdigest(),
        "implementation_sha256": {
            name: hashlib.sha256((Path(__file__).parents[2] / name).read_bytes()).hexdigest()
            for name in (
                "src/skriller/qualification/identity.py",
                "src/skriller/qualification/service.py",
                "src/skriller/qualification/criteria.py",
                "src/skriller/qualification/contacts.py",
            )
        },
        "recorded_at": datetime.now(UTC).isoformat(),
        "accuracy_definition": "Common eligibility accuracy counts all cases; exact_label_accuracy separately requires the exact labelled status/decision, including near matches and unknowns.",
        "exact_label_denominator": len(rows),
        "exact_label_correct": correct,
        "exact_label_accuracy": correct / len(rows),
        "accepted_denominator": predicted_positive,
        "true_positive": true_positive,
        "precision": true_positive / predicted_positive if predicted_positive else None,
        "cases": rows,
        "model_calls": 0,
        "source_calls": 0,
    }
    destination = tmp_path / f"{dimension}-quality.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    if os.environ.get("SKRILLER_WRITE_QUALITY_REPORTS") == "1":
        Path(f"docs/completions/{dimension.upper()}-QUALITY-LOCAL.json").write_text(
            destination.read_text()
        )
    assert correct == len(rows), str(destination)
    assert predicted_positive > 0 and report["precision"] >= 0.9, str(destination)


def test_labelled_qualification_corpus_uses_actual_scoped_claims_and_evidence(database, tmp_path):
    corpus = json.loads(CORPUS.read_text())
    rows = []
    for case in corpus["qualification"]:
        actor = "quality-" + uuid4().hex
        workspace = database.create_workspace(actor, "Synthetic qualification quality")["id"]
        with database.tenant(actor, workspace) as session:
            entity = ResearchRepository.entity(
                session,
                case.get("kind", "person"),
                "Synthetic Entity",
                attributes={"_source_resource_type": case["resource"]}
                if "resource" in case
                else {},
            )
            for field, value in case["facts"]:
                _seed_fact(session, entity["id"], field, value, case)

            plan = SearchPlan(
                workspace_id=UUID(workspace),
                conversation_id=uuid4(),
                revision=1,
                entity_type=case.get("entity_type", "person"),
                must_have=_criteria(case, "criteria"),
                exclusions=_criteria(case, "exclusions"),
                preferences=_criteria(case, "preferences"),
                freshness_days=case.get("freshness_days"),
            )
            fit = qualify_entity(session, plan, entity["id"])
            rows.append(
                {
                    "id": case["id"],
                    "expected": "accept" if case["expected"] == "confirmed" else "reject",
                    "outcome": "accepted" if fit.status == "confirmed" else "rejected",
                    "expected_status": case["expected"],
                    "observed_status": fit.status,
                    "unknown_criteria": sum(
                        item.outcome == "unknown" for item in (*fit.essential, *fit.exclusions)
                    ),
                    "exact_label_correct": fit.status == case["expected"],
                }
            )
    _report("qualification", corpus, rows, tmp_path)


def test_labelled_identity_corpus_uses_actual_scoped_claims_and_evidence(database, tmp_path):
    corpus = json.loads(CORPUS.read_text())
    rows = []
    for case in corpus["identity"]:
        actor = "quality-" + uuid4().hex
        workspace = database.create_workspace(actor, "Synthetic identity quality")["id"]
        with database.tenant(actor, workspace) as session:
            left = ResearchRepository.entity(session, case.get("kind", "person"), "Same Name")
            right = ResearchRepository.entity(
                session, case.get("right_kind", case.get("kind", "person")), "Same Name"
            )
            for side, entity in (("left", left), ("right", right)):
                for field, value in case[side]:
                    _seed_fact(session, entity["id"], field, value, case)
            decision = compare(session, left["id"], right["id"])
            rows.append(
                {
                    "id": case["id"],
                    "expected": "accept" if case["expected"] else "reject",
                    "outcome": "accepted" if decision.eligible else "rejected",
                    "observed_reason": decision.reason,
                    "exact_label_correct": decision.eligible == case["expected"],
                }
            )
    _report("identity", corpus, rows, tmp_path)
