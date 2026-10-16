import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "quality_reports", ROOT / "scripts/quality_reports.py"
)
quality_reports = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(quality_reports)
ReportError = quality_reports.ReportError
aggregate = quality_reports.aggregate
validate_repair = quality_reports.validate_repair


def test_existing_scalar_reports_keep_independent_denominators_and_unmeasured_groups():
    result = aggregate(
        [
            ("field_extraction", ROOT / "docs/completions/OLLAMA-llama3.2-3b-benchmark.json"),
            ("repair", ROOT / "docs/completions/REPAIR-QUALITY-LOCAL-INITIAL.json"),
            ("repair", ROOT / "docs/completions/REPAIR-QUALITY-LOCAL-STABLE-ATTRIBUTES.json"),
        ]
    )
    assert result["dimensions"]["field_extraction"]["status"] == "measured"
    extraction = result["dimensions"]["field_extraction"]["sources"]["synthetic_fixture"]
    assert extraction["run_denominators"] == [5]
    repair = result["dimensions"]["repair"]["sources"]["synthetic_fixture"]
    assert repair["run_denominators"] == [24, 24]
    assert [run["field_accuracy"] for run in repair["runs_summary"]] == [0.7, 0.7]
    for dimension in ("qualification", "identity"):
        assert result["dimensions"][dimension] == {
            "status": "unmeasured",
            "unmeasured_reason": "No compatible labelled report supplied.",
            "sources": {},
        }


def test_repair_validation_rejects_missing_cases_even_when_scalar_counts_look_valid():
    report = json.loads((ROOT / "docs/completions/REPAIR-QUALITY-LOCAL.json").read_text())
    report["cases"].pop(0)
    with pytest.raises(ReportError, match="changed_page_denominator"):
        validate_repair(report)


def test_repair_validation_rejects_duplicate_ids_and_invalid_outcomes():
    report = json.loads((ROOT / "docs/completions/REPAIR-QUALITY-LOCAL.json").read_text())
    report["cases"][1]["id"] = report["cases"][0]["id"]
    with pytest.raises(ReportError, match="unique"):
        validate_repair(report)
    report["cases"][1]["id"] = "unique-again"
    report["cases"][1]["outcome"] = "success-ish"
    with pytest.raises(ReportError, match="unsupported repair outcome"):
        validate_repair(report)


def test_source_groups_are_explicit_and_platform_claims_are_not_inferred():
    result = aggregate([("repair", ROOT / "docs/completions/REPAIR-QUALITY-LOCAL.json")])
    assert list(result["dimensions"]["repair"]["sources"]) == ["synthetic_fixture"]
    run = result["runs"][0]
    assert run["source_group"] == "synthetic_fixture"
    assert "linkedin" not in run["source_group"]


@pytest.mark.parametrize("dimension", ["qualification", "identity"])
def test_common_report_adapter_keeps_unknown_and_unexecuted_in_source_denominator(
    dimension, tmp_path
):
    report_path = tmp_path / f"{dimension}.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dimension": dimension,
                "source_group": "synthetic_fixture",
                "model_mode": "deterministic_fixture",
                "cases": [
                    {"id": "positive", "expected": "accept", "outcome": "accepted"},
                    {"id": "negative", "expected": "reject", "outcome": "rejected"},
                    {"id": "ambiguous", "expected": "accept", "outcome": "unknown"},
                    {"id": "deferred", "expected": "reject", "outcome": "not_executed"},
                ],
            }
        )
    )
    result = aggregate([(dimension, report_path)])
    source = result["dimensions"][dimension]["sources"]["synthetic_fixture"]
    summary = source["runs_summary"][0]
    assert source["run_denominators"] == [4]
    assert summary["positive_denominator"] == 2
    assert summary["negative_denominator"] == 2
    assert summary["outcomes"] == {
        "accepted": 1,
        "not_executed": 1,
        "rejected": 1,
        "unknown": 1,
    }
    assert summary["correct"] == 2
    assert summary["accuracy"] == 0.5
    assert summary["accepted_denominator"] == 1 and summary["precision"] == 1.0


def test_common_report_rejects_duplicate_case_ids(tmp_path):
    path = tmp_path / "identity.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dimension": "identity",
                "cases": [
                    {"id": "duplicate", "expected": "accept", "outcome": "accepted"},
                    {"id": "duplicate", "expected": "reject", "outcome": "rejected"},
                ],
            }
        )
    )
    with pytest.raises(ReportError, match="unique"):
        aggregate([("identity", path)])


def test_adversarial_wrong_target_is_retained_as_failed_evidence():
    report = json.loads((ROOT / "docs/completions/REPAIR-QUALITY-LOCAL.json").read_text())
    case = next(row for row in report["cases"] if row["label"] == "reject")
    case["outcome"] = "silent_wrong"
    report["silent_wrong_matches"] += 1
    report["adversarial_rejected"] -= 1
    report["gate_passed"] = False
    result = validate_repair(report)
    assert result["denominator"] == 24
    assert result["outcomes"]["silent_wrong"] == report["silent_wrong_matches"]
    assert result["gate_passed"] is False


def test_report_limits_reject_oversized_file_and_case_list(tmp_path):
    path = tmp_path / "too-large.json"
    path.write_bytes(b" " * (quality_reports.MAX_REPORT_BYTES + 1))
    with pytest.raises(ReportError, match="2 MiB"):
        aggregate([("identity", path)])
    path.write_text(
        json.dumps({"schema_version": 1, "dimension": "identity", "cases": [{}] * 1001})
    )
    with pytest.raises(ReportError, match="1–1000"):
        aggregate([("identity", path)])
