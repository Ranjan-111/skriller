import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "ticket_status", Path(__file__).parents[2] / "scripts/ticket_status.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture_root(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "tickets.json").write_text(
        json.dumps({"tickets": [{"id": "SKR-001", "status": "planned"}]})
    )
    (docs / "IMPLEMENTATION_TICKETS.md").write_text("# Tickets\n")
    (docs / "proof.md").write_text("Actual passed check\n")
    return tmp_path


def test_cannot_close_with_unresolved_required_check(tmp_path):
    root = fixture_root(tmp_path)
    with pytest.raises(ValueError, match="Done requires"):
        module.update(
            "SKR-001",
            "done",
            reports=["docs/proof.md"],
            checks=["unit checks passed"],
            blockers=["real database pending"],
            root=root,
        )
    data = json.loads((root / "docs/tickets.json").read_text())
    assert data["tickets"][0]["status"] == "planned"


def test_verified_ticket_records_actual_evidence(tmp_path):
    root = fixture_root(tmp_path)
    module.update(
        "SKR-001",
        "done",
        reports=["docs/proof.md"],
        checks=["required acceptance passed"],
        blockers=[],
        root=root,
    )
    assert "done" in (root / "docs/TICKET_STATUS.md").read_text()
    data = json.loads((root / "docs/tickets.json").read_text())
    assert data["tickets"][0]["verification"]["remaining"] == []
