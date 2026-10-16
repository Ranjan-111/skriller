"""Pure bounded owner-report response contracts."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from skriller.analytics.google import AnalyticsUnavailable
from skriller.analytics.reports import ReportRequest, parse_rows

REQUEST = {"start_date": "2026-01-01", "end_date": "2026-01-02", "metrics": ["views"]}
RAW = {
    "kind": "youtubeAnalytics#resultTable",
    "columnHeaders": [
        {"name": "day", "columnType": "DIMENSION", "dataType": "STRING"},
        {"name": "views", "columnType": "METRIC", "dataType": "INTEGER"},
    ],
    "rows": [["2026-01-01", 1]],
}


@pytest.mark.parametrize(
    "change",
    [
        {"end_date": "2026-02-01"},
        {"start_date": "2026-01-03"},
        {"end_date": "2999-01-01"},
        {"metrics": ["views", "views"]},
        {"metrics": ["views&owner=other"]},
        {"owner": "other"},
    ],
)
def test_report_request_bounds_before_source_calls(change):
    with pytest.raises(ValidationError):
        ReportRequest.model_validate({**REQUEST, **change})


@pytest.mark.parametrize(
    "kind",
    [
        "negative",
        "boolean",
        "nan",
        "fractional_count",
        "wrong_day",
        "duplicate_day",
        "reordered_header",
        "wrong_type",
        "compact_date",
    ],
)
def test_report_response_does_not_coerce_or_invent_metrics(kind):
    raw = deepcopy(RAW)
    if kind == "negative":
        raw["rows"][0][1] = -1
    if kind == "boolean":
        raw["rows"][0][1] = True
    if kind == "nan":
        raw["rows"][0][1] = float("nan")
    if kind == "fractional_count":
        raw["rows"][0][1] = 1.5
    if kind == "wrong_day":
        raw["rows"][0][0] = "2026-02-01"
    if kind == "duplicate_day":
        raw["rows"] *= 2
    if kind == "reordered_header":
        raw["columnHeaders"].reverse()
    if kind == "wrong_type":
        raw["columnHeaders"][1]["dataType"] = "STRING"
    if kind == "compact_date":
        raw["rows"][0][0] = "20260101"
    with pytest.raises(AnalyticsUnavailable):
        parse_rows(raw, ReportRequest.model_validate(REQUEST), ["views"])


def test_empty_provider_report_preserves_missing_data_instead_of_zero():
    raw = {**RAW, "rows": []}
    assert parse_rows(raw, ReportRequest.model_validate(REQUEST), ["views"]) == []
