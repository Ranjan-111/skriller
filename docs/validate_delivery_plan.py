"""Validate planning artifacts. This does not execute application tests."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote


def validate(root: Path, ticket_path: Path) -> dict:
    data = json.loads(ticket_path.read_text())
    tickets = data["tickets"]
    source_map = json.loads((root / "docs/reuse_sources.json").read_text())["sources"]
    by_id = {ticket["id"]: ticket for ticket in tickets}
    if len(by_id) != len(tickets):
        raise ValueError("Duplicate ticket ID")
    allowed_phases = {"P0": 0, "P1": 1, "P2": 2}
    expected_requirements = {f"FR-{n:02}" for n in range(1, 17)}
    covered = set()
    for ticket in tickets:
        identity = ticket["id"]
        if not re.fullmatch(r"SKR-\d{3}", identity):
            raise ValueError(f"Invalid ID: {identity}")
        if ticket["phase"] not in allowed_phases:
            raise ValueError(f"Invalid phase: {identity}")
        for field in ("title", "scope", "requirements", "acceptance_criteria", "test_cases"):
            if not ticket.get(field):
                raise ValueError(f"Missing {field}: {identity}")
        if len(ticket["acceptance_criteria"]) < 2 or len(ticket["test_cases"]) < 2:
            raise ValueError(f"Insufficient acceptance/verification cases: {identity}")
        for case in ticket["test_cases"]:
            if not all(case.get(field) for field in ("kind", "scenario", "expected")):
                raise ValueError(f"Incomplete verification case: {identity}")
        covered.update(ticket["requirements"])
        for source in ticket["reuse_ids"]:
            if source not in source_map:
                raise ValueError(f"Unknown reuse source {source}: {identity}")
        for dependency in ticket["depends_on"]:
            if dependency not in by_id:
                raise ValueError(f"Missing dependency {dependency}: {identity}")
            if allowed_phases[by_id[dependency]["phase"]] > allowed_phases[ticket["phase"]]:
                raise ValueError(f"Earlier phase depends on later phase: {identity}")
    if covered != expected_requirements:
        raise ValueError(f"PRD coverage mismatch: {covered ^ expected_requirements}")

    visiting, visited, order = set(), set(), []

    def visit(identity: str) -> None:
        if identity in visiting:
            raise ValueError(f"Dependency cycle at {identity}")
        if identity in visited:
            return
        visiting.add(identity)
        for dependency in by_id[identity]["depends_on"]:
            visit(dependency)
        visiting.remove(identity)
        visited.add(identity)
        order.append(identity)

    for identity in by_id:
        visit(identity)

    mapped_paths = set()
    for source, entry in source_map.items():
        for value in entry["code_paths"] + entry["test_paths"]:
            path = root / value
            if not path.exists():
                raise ValueError(f"Missing source/test path {value}: {source}")
            mapped_paths.add(value)

    document = root / "docs/IMPLEMENTATION_TICKETS.md"
    rendered = document.read_text()
    rendered_ids = re.findall(r"^#### (SKR-\d{3}) —", rendered, re.M)
    if rendered_ids != [ticket["id"] for ticket in tickets]:
        raise ValueError("Markdown and JSON ticket order/IDs disagree")
    for path in (root / "docs").glob("*.md"):
        body = path.read_text()
        if body.count("```") % 2:
            raise ValueError(f"Unclosed code fence: {path.name}")
        for target in re.findall(r"\]\(([^)]+)\)", body):
            if re.match(r"^[a-z]+://", target):
                continue
            local, _, fragment = target.partition("#")
            target_path = path.parent / unquote(local) if local else path
            if not target_path.exists():
                raise ValueError(f"Broken local link {target}: {path.name}")
            if fragment.startswith("skr-"):
                if f'id="{fragment}"' not in target_path.read_text():
                    raise ValueError(f"Broken ticket anchor {target}: {path.name}")

    inventory = json.loads((root / "docs/REFERENCE_INVENTORY.json").read_text())
    checked_files = 0
    for project in inventory["projects"]:
        records = project["files"]
        for record in records:
            path = root / record["path"]
            if not path.is_file():
                raise ValueError(f"Reference file missing: {record['path']}")
            if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
                raise ValueError(f"Reference content changed: {record['path']}")
            checked_files += 1
        fingerprint = "\n".join(
            f"{record['path']}\0{record['sha256']}" for record in records
        )
        if hashlib.sha256(fingerprint.encode()).hexdigest() != project["snapshot_sha256"]:
            raise ValueError(f"Inventory fingerprint invalid: {project['directory']}")

    return {
        "status": "PASS",
        "tickets": len(tickets),
        "phases": dict(Counter(ticket["phase"] for ticket in tickets)),
        "planned_test_cases": sum(len(ticket["test_cases"]) for ticket in tickets),
        "requirements_covered": sorted(covered),
        "reuse_groups": len(source_map),
        "unique_source_test_paths": len(mapped_paths),
        "reference_files_unchanged": checked_files,
        "dependency_graph": "acyclic",
        "first_dependency_order": order[:12],
        "application_tests_executed_by_this_check": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickets", type=Path)
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parent.parent
    try:
        result = validate(workspace, args.tickets or workspace / "docs/tickets.json")
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        parser.exit(1, f"FAIL: {exc}\n")
    print(json.dumps(result, indent=2))
