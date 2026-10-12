"""Cross-process leases; throttling uses the attributed, copied Scrapling implementation.

Caps live in owner-managed SQL, not caller-supplied parameters. Leases recover
capacity after worker death. Callers must bound I/O to the lease expiry and stop
I/O before releasing; an expired token cannot update cadence or release a successor.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from time import monotonic
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from scrapling.spiders.throttle import AutoThrottle, parse_retry_after
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class CapacityLease:
    id: str
    ttl_seconds: int
    deadline_monotonic: float


class CapacityUnavailable(RuntimeError):
    """Resource cap or persisted cadence currently prevents dispatch."""


def acquire(
    session: Session,
    job_id: str,
    *,
    kind: Literal["http", "browser", "model"],
    source: str,
    host: str,
    ttl_seconds: int = 60,
    minimum_interval: float = 0,
) -> CapacityLease:
    if not math.isfinite(minimum_interval) or not 0 <= minimum_interval <= 86400:
        raise ValueError("Invalid source minimum interval")
    started = monotonic()
    token = session.execute(
        sa.text("SELECT capacity_acquire(:workspace,:job,:kind,:source,:host,:ttl,:floor)"),
        {
            "workspace": session.info["workspace_id"],
            "job": str(UUID(job_id)),
            "kind": kind,
            "source": source.lower(),
            "host": host.lower(),
            "ttl": ttl_seconds,
            "floor": minimum_interval,
        },
    ).scalar_one()
    if token is None:
        raise CapacityUnavailable("Shared capacity or source cadence exhausted")
    return CapacityLease(str(token), ttl_seconds, started + ttl_seconds)


def release(
    session: Session,
    lease: CapacityLease,
    *,
    latency: float | None = None,
    ok: bool = True,
    headers: Mapping[str, str] | None = None,
    minimum_interval: float = 0,
) -> bool:
    """Persist copied adaptive throttle feedback, or release an unused slot.

    Retry-After is a separate floor, so adaptive clamping never shortens a
    server-requested wait. Malformed/nonfinite numeric
    headers fail conservatively with the maximum supported backoff.
    """
    if latency is not None and (not math.isfinite(latency) or latency < 0):
        raise ValueError("Latency must be finite and nonnegative")
    if not math.isfinite(minimum_interval) or not 0 <= minimum_interval <= 86400:
        raise ValueError("Invalid source minimum interval")
    row = (
        session.execute(
            sa.text("SELECT * FROM capacity_observe(:workspace,:lease)"),
            {"workspace": session.info["workspace_id"], "lease": str(UUID(lease.id))},
        )
        .mappings()
        .first()
    )
    if row is None:
        return False
    delay = 0.0
    if latency is not None:
        retry = parse_retry_after(headers or {})
        if retry is not None:
            retry = min(retry, 86400) if math.isfinite(retry) else 86400
        throttle = AutoThrottle(start_delay=0, max_delay=86400)
        throttle.delays[row["host"]] = row["delay"]
        delay = throttle.record(row["host"], latency, ok, floor=minimum_interval, retry_after=retry)
        if retry is not None:
            delay = max(delay, retry)
    return bool(
        session.execute(
            sa.text("SELECT capacity_finish(:workspace,:lease,:delay)"),
            {"workspace": session.info["workspace_id"], "lease": lease.id, "delay": delay},
        ).scalar_one()
    )
