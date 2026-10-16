"""Labelled changed-page accuracy over the real copied repair graph and worker.

Default tests use a labelled controlled model to test the evaluator/workflow.
Explicit local mode measures actual Ollama proposals; the report labels the mode.
"""

import hashlib
import json
import os
from pathlib import Path
from time import monotonic

import pytest
from scrapling import Selector
from test_template_repair_workflow import Model, requested, setup

from skriller.extraction.models import LocalStructuredModel, ModelBounds
from skriller.jobs.budget import current_usage
from skriller.research.adaptive_templates import ReviewedTemplate
from skriller.research.template_registry import publish_template, selected_templates
from skriller.research.template_repair import RepairInput, execute_template_repair, repair_view

pytestmark = pytest.mark.integration_db
CORPUS = Path(__file__).parents[1] / "fixtures/repair/quality.json"


def test_labelled_twenty_page_repair_accuracy_and_adversarial_rejection(database, tmp_path):
    from datetime import UTC, datetime
    from uuid import UUID

    corpus_bytes = CORPUS.read_bytes()
    corpus = json.loads(corpus_bytes)
    positives = [item for item in corpus["cases"] if item["expected"] == "correct"]
    assert len(positives) >= 20
    local = os.environ.get("SKRILLER_RUN_LOCAL_MODEL_TESTS") == "1"
    started = monotonic()
    measured = []
    for case in corpus["cases"]:
        if monotonic() - started > 120:
            measured.append(
                {
                    "id": case["id"],
                    "label": case["expected"],
                    "outcome": "not_executed",
                    "calls": 0,
                    "tokens": 0,
                }
            )
            continue
        actor, workspace, storage, template, _ = setup(database, tmp_path / case["id"])
        # Use exactly the labelled literal and original mapping for this case.
        template = ReviewedTemplate.model_validate(
            {
                **template.model_dump(mode="json"),
                "template_version": 2,
                "fields": [{**template.fields[0].model_dump(), "expected_text": case["value"]}],
            }
        )
        with database.tenant(actor, workspace) as session:
            publish_template(session, template, expected_version=1)
            ids = [
                storage.store(
                    session,
                    html.encode(),
                    source_url=template.source_url,
                    source_platform="web",
                    collected_at=datetime.now(UTC),
                )["id"]
                for html in [case["current"], case["old"]]
            ]
        inputs = RepairInput(
            expected_version=2,
            field_identifier="name",
            current_evidence_id=UUID(ids[0]),
            regression_evidence_ids=[UUID(ids[1])],
        )
        job, task = requested(database, actor, workspace, template, inputs)
        model = LocalStructuredModel(
            ModelBounds(timeout_seconds=10, output_tokens=128),
            model_instance=None if local else Model(case["gold_css"]),
        )
        outcome = execute_template_repair(database, task, storage=storage, model=model)
        with database.tenant(actor, workspace) as session:
            view = repair_view(session, job["id"])
            assert selected_templates(session)[0].template_version == 2
            counters = current_usage(session, job["id"])[1]
        correct = False
        if view.proposal is not None:
            doc = Selector(case["current"], adaptive=False)
            prediction = doc.css(view.proposal.fields[0].css)
            gold = doc.css(case["gold_css"])
            correct = (
                case["expected"] == "correct"
                and len(prediction) == len(gold) == 1
                and prediction[0].generate_full_xpath_selector
                == gold[0].generate_full_xpath_selector
                and prediction[0].get_all_text(separator=" ", strip=True) == case["value"]
            )
        measured.append(
            {
                "id": case["id"],
                "label": case["expected"],
                "outcome": "correct"
                if correct
                else "silent_wrong"
                if view.proposal is not None
                else "missing"
                if case["expected"] == "correct"
                else "rejected",
                "reason": view.reason,
                "worker_status": outcome["status"],
                "calls": counters["llm_calls"],
                "tokens": counters["tokens"],
            }
        )
    correct = sum(row["outcome"] == "correct" for row in measured)
    silent_wrong = sum(row["outcome"] == "silent_wrong" for row in measured)
    rejected = sum(row["outcome"] == "rejected" for row in measured)
    report = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "repair_code_sha256": hashlib.sha256(
            (Path(__file__).parents[2] / "src/skriller/extraction/repair.py").read_bytes()
        ).hexdigest(),
        "scope": corpus["scope"],
        "corpus_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
        "model_mode": "actual_local_ollama_llama3.2:3b" if local else "controlled_labelled_fixture",
        "accuracy_definition": "Exact labelled element path and literal value; equivalent nested elements count as target mismatches under this conservative metric.",
        "required_field_accuracy": 0.9,
        "allowed_silent_target_mismatches": 0,
        "evaluation_scope": "Development fixture acceptance, not a held-out or representative platform benchmark",
        "prompt_revision": "source_attribute_enum_nested_guard",
        "changed_page_denominator": len(positives),
        "correct_fields": correct,
        "field_accuracy": correct / len(positives),
        "silent_wrong_matches": silent_wrong,
        "missing_fields": sum(row["outcome"] == "missing" for row in measured),
        "not_executed": sum(row["outcome"] == "not_executed" for row in measured),
        "adversarial_denominator": len(measured) - len(positives),
        "adversarial_rejected": rejected,
        "actual_metered_calls": sum(row["calls"] for row in measured),
        "metered_tokens": sum(row["tokens"] for row in measured),
        "elapsed_seconds": round(monotonic() - started, 3),
        "cases": measured,
    }
    report["gate_passed"] = (
        correct / len(positives) >= 0.9
        and silent_wrong == 0
        and rejected == report["adversarial_denominator"]
    )
    report_path = tmp_path / "repair-quality.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    if local:
        Path("docs/completions/REPAIR-QUALITY-LOCAL.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}))
    assert correct / len(positives) >= 0.9, str(report_path)
    assert silent_wrong == 0, str(report_path)
    assert rejected == report["adversarial_denominator"], str(report_path)
    assert report["actual_metered_calls"] <= len(measured)
