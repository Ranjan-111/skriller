"""Record verified ticket status; never infer completion from code presence."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATES = {"planned", "in_progress", "implemented_pending_verification", "blocked", "done"}


def update(
    ticket_id: str,
    status: str,
    *,
    reports: list[str],
    checks: list[str],
    blockers: list[str],
    root: Path = ROOT,
):
    if status not in STATES:
        raise ValueError("Invalid ticket status")
    if status == "done" and (not reports or not checks or blockers):
        raise ValueError(
            "Done requires verified checks, reports, and no unresolved acceptance blocker"
        )
    for report in reports:
        if not (root / report).is_file():
            raise ValueError(f"Missing evidence report: {report}")
    path = root / "docs/tickets.json"
    data = json.loads(path.read_text())
    ticket = next((item for item in data["tickets"] if item["id"] == ticket_id), None)
    if ticket is None:
        raise ValueError("Unknown ticket")
    ticket.update(
        status=status,
        verification={
            "reports": reports,
            "passed_checks": checks,
            "remaining": blockers,
            "recorded_at": datetime.now(UTC).isoformat(),
        },
    )
    data["status"] = "implementation_in_progress"
    data["implementation_status"] = (
        "Per-ticket status and verification records are authoritative; planned test cases are not themselves passing tests."
    )
    path.write_text(json.dumps(data, indent=2) + "\n")
    render(root, data)


def render(root: Path, data: dict):
    tickets = data["tickets"]
    counts = Counter(item["status"] for item in tickets)
    lines = [
        "# Ticket execution status",
        "",
        "Only tickets with completed scope and verified required checks are marked **done**.",
        "",
        "A passing unit suite does not close a required database, browser, container, or live-source gate.",
        "",
        "Current counts: "
        + ", ".join(f"{count} {state}" for state, count in sorted(counts.items()))
        + ".",
        "",
        "| Ticket | Status | Verified evidence | Remaining acceptance checks |",
        "| --- | --- | --- | --- |",
    ]
    deferred = data.get("user_deferred_gates", [])
    if deferred:
        lines[8:8] = [
            "User-deferred verification gates:",
            "",
            *(f"- {item}" for item in deferred),
            "",
        ]
    for item in tickets:
        verification = item.get("verification", {})
        links = ", ".join(
            f"[report]({report.removeprefix('docs/')})"
            for report in verification.get("reports", [])
        )
        remaining = "; ".join(verification.get("remaining", [])) or (
            "Not started" if item["status"] == "planned" else "None"
        )
        lines.append(f"| {item['id']} | {item['status']} | {links or '—'} | {remaining} |")
    (root / "docs/TICKET_STATUS.md").write_text("\n".join(lines) + "\n")
    backlog = root / "docs/IMPLEMENTATION_TICKETS.md"
    body = backlog.read_text()
    for item in tickets:
        pattern = rf"(#### {item['id']} —[^\n]+\n\n\*\*Phase:\*\*[^\n]*\*\*Status:\*\* )[^\n]+"
        body = re.sub(pattern, lambda match, state=item["status"]: match.group(1) + state, body)
    body = body.replace(
        "All tickets are **planned**, not implemented.",
        "Implementation is in progress; [verified execution status](TICKET_STATUS.md) is authoritative.",
    )
    body = re.sub(
        r"All include explicit verification scenarios\. Application tests are \*\*not written or run yet\*\*\.",
        "All include verification scenarios; actual results are recorded per ticket in the execution status.",
        body,
    )
    backlog.write_text(body)


if __name__ == "__main__":
    data = json.loads((ROOT / "docs/tickets.json").read_text())
    render(ROOT, data)
    print(dict(Counter(item["status"] for item in data["tickets"])))
