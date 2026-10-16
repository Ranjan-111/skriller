"""Bounded owner-channel metrics with exact values and explicit data availability."""

import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from typing import Literal
from urllib.parse import urlencode
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from skriller.analytics.google import SCOPES, AnalyticsUnavailable
from skriller.analytics.service import now, refresh_grant

METRICS = {"views": "count", "estimatedMinutesWatched": "minutes", "averageViewDuration": "seconds"}


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_date: date
    end_date: date
    metrics: list[str] = Field(min_length=1, max_length=5)

    @field_validator("metrics")
    @classmethod
    def bounded_metrics(cls, values):
        if len(set(values)) != len(values) or any(
            not value or len(value) > 64 or not value.isascii() or not value.isalnum()
            for value in values
        ):
            raise ValueError("Unique bounded metric names required")
        return values

    @model_validator(mode="after")
    def bounded_dates(self):
        if (
            not 0 <= (self.end_date - self.start_date).days < 31
            or self.end_date >= datetime.now(ZoneInfo("America/Los_Angeles")).date()
        ):
            raise ValueError("Historical date range must contain at most31 days")
        return self


class MetricRow(BaseModel):
    day: date
    metrics: dict[str, int | float]


class AnalyticsReport(BaseModel):
    status: Literal["available", "partial", "unavailable"]
    grant_id: UUID
    channel_id: str
    start_date: date
    end_date: date
    timezone: Literal["America/Los_Angeles"] = "America/Los_Angeles"
    currency: None = None
    coverage_complete: Literal[False] = False
    availability: Literal["provider_returned_days_only"] = "provider_returned_days_only"
    rows: list[MetricRow]
    units: dict[str, str]
    unavailable_metrics: dict[str, str]
    source_url: str
    source_platform: Literal["youtube_analytics"] = "youtube_analytics"
    collected_at: datetime
    response_sha256: str | None
    summary: list[str]
    summary_status: Literal["literal_metrics_only"] = "literal_metrics_only"


@dataclass(frozen=True)
class VerifiedReport:
    report: AnalyticsReport
    owner_id: str
    workspace_id: str
    grant_version: int


def parse_rows(raw, request, metrics):
    if (
        not isinstance(raw, dict)
        or len(json.dumps(raw).encode()) > 65536
        or raw.get("kind") != "youtubeAnalytics#resultTable"
    ):
        raise AnalyticsUnavailable("analytics_report_schema_invalid")
    headers = raw.get("columnHeaders")
    if not isinstance(headers, list) or len(headers) != len(metrics) + 1:
        raise AnalyticsUnavailable("analytics_report_schema_invalid")
    expected = ["day", *metrics]
    for index, header in enumerate(headers):
        if (
            not isinstance(header, dict)
            or header.get("name") != expected[index]
            or header.get("columnType") != ("DIMENSION" if index == 0 else "METRIC")
            or header.get("dataType") not in ({"STRING"} if index == 0 else {"INTEGER", "FLOAT"})
        ):
            raise AnalyticsUnavailable("analytics_report_schema_invalid")
    values = raw.get("rows", [])
    if not isinstance(values, list) or len(values) > 31:
        raise AnalyticsUnavailable("analytics_report_schema_invalid")
    rows, seen = [], set()
    for row in values:
        if not isinstance(row, list) or len(row) != len(expected) or not isinstance(row[0], str):
            raise AnalyticsUnavailable("analytics_report_schema_invalid")
        try:
            day = date.fromisoformat(row[0])
        except ValueError:
            raise AnalyticsUnavailable("analytics_report_schema_invalid") from None
        if (
            not request.start_date <= day <= request.end_date
            or day.isoformat() != row[0]
            or day in seen
            or (rows and day <= rows[-1].day)
        ):
            raise AnalyticsUnavailable("analytics_report_schema_invalid")
        seen.add(day)
        numeric = {}
        for metric, value in zip(metrics, row[1:], strict=True):
            if (
                type(value) not in {int, float}
                or not math.isfinite(value)
                or not 0 <= value <= 10**18
                or (metric == "views" and type(value) is not int)
            ):
                raise AnalyticsUnavailable("analytics_report_schema_invalid")
            numeric[metric] = value
        for index, value in enumerate(row[1:], start=1):
            if headers[index]["dataType"] == "INTEGER" and type(value) is not int:
                raise AnalyticsUnavailable("analytics_report_schema_invalid")
        rows.append(MetricRow(day=day, metrics=numeric))
    return rows


def read_report(
    database, store, config, provider, actor, workspace, identifier, request: ReportRequest
):
    supported = [name for name in request.metrics if name in METRICS]
    unavailable = {name: "unsupported_metric" for name in request.metrics if name not in METRICS}
    with database.tenant(actor, workspace) as session:
        row = store.get(session, identifier)
        current = now(session)
        if (
            row["state"] != "active"
            or row["expires_at"] <= current
            or set(row["scopes"]) != set(SCOPES)
        ):
            raise AnalyticsUnavailable()
        expired = row["access_expires_at"] <= current
    if expired and supported:
        refresh_grant(database, store, config, provider, actor, workspace, identifier)
    with database.tenant(actor, workspace) as session:
        row = store.get(session, identifier)
        if row["state"] != "active" or row["expires_at"] <= now(session):
            raise AnalyticsUnavailable()
        # Unsupported-only requests make no token refresh or Google request.
        token = store.access(session, identifier)[1] if supported else None
        version, channel_id, collected_at = row["version"], row["channel_id"], now(session)
    params = {
        "ids": "channel==" + channel_id,
        "startDate": request.start_date.isoformat(),
        "endDate": request.end_date.isoformat(),
        "dimensions": "day",
        "metrics": ",".join(supported),
    }
    source_url = "https://youtubeanalytics.googleapis.com/v2/reports?" + urlencode(params)
    raw, rows, response_hash = None, [], None
    if supported:
        try:
            raw = provider.report(
                token, channel_id, request.start_date, request.end_date, tuple(supported)
            )
            rows = parse_rows(raw, request, supported)
            response_hash = sha256(
                json.dumps(raw, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            ).hexdigest()
        except AnalyticsUnavailable as exc:
            unavailable.update({name: exc.code for name in supported})
        except Exception:  # noqa: BLE001 - malformed provider data never leaks or becomes a metric
            unavailable.update({name: "analytics_provider_unavailable" for name in supported})
    with database.tenant(actor, workspace) as session:
        current_row = store.get(session, identifier)
        if (
            current_row["state"] != "active"
            or current_row["version"] != version
            or current_row["expires_at"] <= now(session)
        ):
            raise AnalyticsUnavailable()
        if supported and current_row["access_expires_at"] <= now(session):
            raise AnalyticsUnavailable()
        collected_at = now(session)
        if any(
            code in {"analytics_authorization_expired", "analytics_provider_denied"}
            for code in unavailable.values()
        ):
            store.revoke(session, identifier)
    if not rows:
        unavailable.update(
            {name: unavailable.get(name, "report_data_unavailable") for name in supported}
        )
    report = AnalyticsReport(
        status=("partial" if unavailable else "available") if rows else "unavailable",
        grant_id=identifier,
        channel_id=channel_id,
        start_date=request.start_date,
        end_date=request.end_date,
        rows=rows,
        units={metric: METRICS[metric] for metric in supported},
        unavailable_metrics=unavailable,
        source_url=source_url,
        collected_at=collected_at,
        response_sha256=response_hash,
        summary=[
            item.day.isoformat()
            + ": "
            + "; ".join(f"{key}={value} {METRICS[key]}" for key, value in item.metrics.items())
            for item in rows
        ],
    )
    return VerifiedReport(report, actor, workspace, version)
