"""Validate and aggregate bounded scalar quality evidence without inventing data.

Each report remains an independent run. Repeated runs are never pooled into a
larger denominator, and dimensions without labelled observations remain marked
unmeasured rather than receiving a synthetic zero score.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

DIMENSIONS = ("field_extraction", "qualification", "identity", "repair")
REPAIR_OUTCOMES = {"correct", "missing", "silent_wrong", "rejected", "not_executed"}
EXTRACTION_OUTCOMES = {"passed", "quality_failed", "not_executed"}
CASE_OUTCOMES = {"accepted", "rejected", "unknown", "not_executed"}
MAX_REPORT_BYTES = 2 * 1024 * 1024
MAX_CASES = 1000


def _cases(value, name):
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_CASES:
        raise ReportError(f"{name} needs 1–{MAX_CASES} case rows")
    for row in value:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("id"), str)
            or not 1 <= len(row["id"]) <= 200
        ):
            raise ReportError("each case needs a bounded nonempty string id")
    return value


class ReportError(ValueError):
    """A supplied quality report is malformed or internally inconsistent."""


def _integer(report: dict[str, Any], key: str, *, minimum: int = 0) -> int:
    value = report.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ReportError(f"{key} must be an integer >= {minimum}")
    return value


def _finite_number(report: dict[str, Any], key: str) -> float:
    value = report.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReportError(f"{key} must be numeric")
    number = float(value)
    if not 0 <= number <= 1:
        raise ReportError(f"{key} must be between 0 and 1")
    return number


def validate_repair(report: dict[str, Any]) -> dict[str, Any]:
    cases = _cases(report.get("cases"), "repair report")
    ids: set[str] = set()
    outcomes: Counter[str] = Counter()
    labels: Counter[str] = Counter()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ReportError("each repair case needs a string id")
        if case["id"] in ids:
            raise ReportError("case ids must be unique within a run")
        ids.add(case["id"])
        outcome = case.get("outcome")
        if not isinstance(outcome, str) or outcome not in REPAIR_OUTCOMES:
            raise ReportError(f"unsupported repair outcome: {outcome!r}")
        if not isinstance(case.get("label"), str) or case["label"] not in {"correct", "reject"}:
            raise ReportError("repair case label must be correct or reject")
        if case["label"] == "reject" and outcome not in {
            "rejected",
            "not_executed",
            "silent_wrong",
        }:
            raise ReportError("adversarial repair outcome contradicts its label")
        if case["label"] == "correct" and outcome == "rejected":
            raise ReportError("positive repair cases cannot have rejected outcome")
        for key in ("calls", "tokens"):
            value = case.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ReportError(f"case {key} must be a non-negative integer")
        outcomes[outcome] += 1
        labels[case["label"]] += 1

    positive_denominator = labels["correct"]
    adversarial_denominator = labels["reject"]
    if positive_denominator == 0:
        raise ReportError("repair report has no positive labelled cases")
    declared = {
        "changed_page_denominator": positive_denominator,
        "correct_fields": outcomes["correct"],
        "silent_wrong_matches": outcomes["silent_wrong"],
        "missing_fields": outcomes["missing"],
        "not_executed": outcomes["not_executed"],
        "adversarial_denominator": adversarial_denominator,
        "adversarial_rejected": outcomes["rejected"],
        "actual_metered_calls": sum(case.get("calls", 0) for case in cases),
        "metered_tokens": sum(case.get("tokens", 0) for case in cases),
    }
    for key, expected in declared.items():
        if _integer(report, key) != expected:
            raise ReportError(f"{key} disagrees with case rows")
    expected_accuracy = outcomes["correct"] / positive_denominator
    if abs(_finite_number(report, "field_accuracy") - expected_accuracy) > 1e-9:
        raise ReportError("field_accuracy disagrees with labelled case rows")
    if not isinstance(report.get("gate_passed"), bool):
        raise ReportError("gate_passed must be boolean")
    required_accuracy = _finite_number(report, "required_field_accuracy")
    allowed_mismatches = _integer(report, "allowed_silent_target_mismatches")
    calculated_gate = (
        expected_accuracy >= required_accuracy
        and outcomes["silent_wrong"] <= allowed_mismatches
        and outcomes["rejected"] == adversarial_denominator
    )
    if report["gate_passed"] != calculated_gate:
        raise ReportError("gate_passed disagrees with declared thresholds and cases")
    if report.get("model_mode") not in {
        "actual_local_ollama_llama3.2:3b",
        "controlled_labelled_fixture",
    }:
        raise ReportError("unknown repair model_mode")
    return {
        "denominator": len(cases),
        "positive_denominator": positive_denominator,
        "adversarial_denominator": adversarial_denominator,
        "outcomes": dict(sorted(outcomes.items())),
        "field_accuracy": expected_accuracy,
        "required_field_accuracy": required_accuracy,
        "allowed_silent_target_mismatches": allowed_mismatches,
        "gate_passed": report["gate_passed"],
        "model_mode": report["model_mode"],
    }


def validate_extraction(report: dict[str, Any]) -> dict[str, Any]:
    rows = _cases(report.get("results"), "extraction report")
    ids: set[str] = set()
    outcomes: Counter[str] = Counter()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ReportError("each extraction result needs a string id")
        if row["id"] in ids:
            raise ReportError("result ids must be unique within a run")
        ids.add(row["id"])
        if not isinstance(row.get("status"), str) or row["status"] not in EXTRACTION_OUTCOMES:
            raise ReportError("unsupported extraction status")
        outcomes[row["status"]] += 1
    denominator = _integer(report, "corpus_size", minimum=1)
    if denominator != len(rows):
        raise ReportError("corpus_size disagrees with result rows")
    correct = _integer(report, "correct_records")
    if correct != outcomes["passed"]:
        raise ReportError("correct_records disagrees with result rows")
    accuracy = _finite_number(report, "record_accuracy")
    if abs(accuracy - correct / denominator) > 1e-9:
        raise ReportError("record_accuracy disagrees with result rows")
    return {
        "denominator": denominator,
        "outcomes": dict(sorted(outcomes.items())),
        "accuracy": accuracy,
        "model_mode": f"{report.get('provider', 'unknown')}:{report.get('model', 'unknown')}",
    }


def validate_case_report(report: dict[str, Any], dimension: str) -> dict[str, Any]:
    """Validate a common labelled report for dimensions without legacy adapters."""
    if (
        type(report.get("schema_version")) is not int
        or report["schema_version"] != 1
        or report.get("dimension") != dimension
    ):
        raise ReportError("common report schema_version/dimension mismatch")
    cases = _cases(report.get("cases"), "common report")
    ids: set[str] = set()
    outcomes: Counter[str] = Counter()
    expected_counts: Counter[str] = Counter()
    correct = 0
    incorrect = 0
    true_positive = 0
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ReportError("each common case needs a string id")
        if case["id"] in ids:
            raise ReportError("case ids must be unique within a run")
        ids.add(case["id"])
        expected = case.get("expected")
        outcome = case.get("outcome")
        if not isinstance(expected, str) or expected not in {"accept", "reject"}:
            raise ReportError("case expected must be accept or reject")
        if not isinstance(outcome, str) or outcome not in CASE_OUTCOMES:
            raise ReportError("unsupported common case outcome")
        if outcome in {"accepted", "rejected"}:
            is_correct = (expected == "accept" and outcome == "accepted") or (
                expected == "reject" and outcome == "rejected"
            )
            correct += int(is_correct)
            incorrect += int(not is_correct)
            true_positive += int(expected == "accept" and outcome == "accepted")
        expected_counts[expected] += 1
        outcomes[outcome] += 1
    denominator = len(cases)
    predicted_positive = outcomes["accepted"]
    precision = true_positive / predicted_positive if predicted_positive else None
    for key, expected_total in (
        ("accepted_denominator", predicted_positive),
        ("true_positive", true_positive),
    ):
        if key in report and _integer(report, key) != expected_total:
            raise ReportError(f"{key} disagrees with case rows")
    if "precision" in report and report["precision"] != precision:
        raise ReportError("precision disagrees with case rows")
    return {
        "denominator": denominator,
        "positive_denominator": expected_counts["accept"],
        "negative_denominator": expected_counts["reject"],
        "accepted_denominator": predicted_positive,
        "true_positive": true_positive,
        "precision": precision,
        "outcomes": dict(sorted(outcomes.items())),
        "correct": correct,
        "incorrect": incorrect,
        # Unknown and unexecuted cases stay in the denominator and do not count
        # as correct, making the reported score conservative and explicit.
        "accuracy": correct / denominator,
        "model_mode": report.get("model_mode", "not_reported"),
    }


def _source_group(report: dict[str, Any]) -> str:
    explicit = report.get("source_group")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    if report.get("synthetic_only") is True or str(report.get("evaluation_scope", "")).startswith(
        "Development fixture"
    ):
        return "synthetic_fixture"
    return "source_unreported"


def aggregate(inputs: list[tuple[str, Path]]) -> dict[str, Any]:
    if len(inputs) > 32:
        raise ReportError("At most 32 reports can be aggregated")
    runs: list[dict[str, Any]] = []
    by_dimension_source: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for dimension, path in inputs:
        if dimension not in DIMENSIONS:
            raise ReportError(f"unsupported dimension: {dimension}")
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_REPORT_BYTES + 1)
            if len(raw) > MAX_REPORT_BYTES:
                raise ReportError("Report exceeds 2 MiB")
            report = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise ReportError(f"cannot read valid JSON report {path}") from exc
        if not isinstance(report, dict):
            raise ReportError(f"report root must be an object: {path}")
        summary = (
            validate_repair(report)
            if dimension == "repair" and "changed_page_denominator" in report
            else validate_extraction(report)
            if dimension == "field_extraction" and "corpus_size" in report
            else validate_case_report(report, dimension)
        )
        source = _source_group(report)
        run = {
            "dimension": dimension,
            "source_group": source,
            "report": path.as_posix(),
            "report_sha256": hashlib.sha256(raw).hexdigest(),
            "scope": report.get("evaluation_scope", report.get("scope", "not_reported")),
            "accuracy_definition": report.get(
                "accuracy_definition",
                "Report-specific labelled outcome accuracy; see original report",
            ),
            **summary,
        }
        runs.append(run)
        by_dimension_source[dimension][source].append(run)

    dimensions: dict[str, Any] = {}
    for dimension in DIMENSIONS:
        sources = by_dimension_source.get(dimension, {})
        dimensions[dimension] = {
            "status": "measured" if sources else "unmeasured",
            "unmeasured_reason": None if sources else "No compatible labelled report supplied.",
            "sources": {
                source: {
                    "runs": len(source_runs),
                    # Keep each corpus denominator separate: repeated runs may
                    # share examples and must not inflate sample size.
                    "run_denominators": [run["denominator"] for run in source_runs],
                    "runs_summary": [
                        {
                            key: run[key]
                            for key in (
                                "report",
                                "report_sha256",
                                "denominator",
                                "positive_denominator",
                                "adversarial_denominator",
                                "negative_denominator",
                                "accepted_denominator",
                                "true_positive",
                                "precision",
                                "outcomes",
                                "field_accuracy",
                                "accuracy",
                                "correct",
                                "incorrect",
                                "gate_passed",
                                "model_mode",
                            )
                            if key in run
                        }
                        for run in source_runs
                    ],
                }
                for source, source_runs in sorted(sources.items())
            },
        }
    return {
        "schema_version": 1,
        "measurement_origin": "Supplied scalar reports; aggregation does not execute or attest model/source calls",
        "runs": runs,
        "dimensions": dimensions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        metavar="DIMENSION=PATH",
        help="repeat for each scalar report",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inputs: list[tuple[str, Path]] = []
    for entry in args.input:
        dimension, separator, name = entry.partition("=")
        if not separator or not name:
            parser.error("--input must be DIMENSION=PATH")
        inputs.append((dimension, Path(name)))
    result = aggregate(inputs)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
