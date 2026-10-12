"""Import and verify attributed source snapshots without touching reference trees."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = {
    "scrapling": ("Scrapling-main", "scrapling"),
    "agent-reach": ("Agent-Reach-main", "agent_reach"),
    "scrapegraph-ai": ("Scrapegraph-ai-main", "scrapegraphai"),
}
METADATA = ("pyproject.toml", "README.md", "LICENSE", "pytest.ini", "MANIFEST.in")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def import_project(project: str, root: Path = ROOT) -> Path:
    folder, package = PROJECTS[project]
    source, target = root / "reference" / folder, root / "third_party" / project
    if target.exists():
        raise ValueError(f"Import destination already exists: {target}")
    target.mkdir(parents=True)
    records = []
    for name in (package, "tests", "examples", *METADATA):
        item = source / name
        if not item.exists():
            continue
        files = sorted(item.rglob("*")) if item.is_dir() else [item]
        for original in files:
            if not original.is_file() or original.is_symlink():
                continue
            if any(part in {"__pycache__", ".git", ".pytest_cache"} for part in original.parts):
                continue
            relative = original.relative_to(source)
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, destination)
            records.append({"path": str(relative), "source": str(original.relative_to(root)),
                            "source_sha256": sha(original), "copied_sha256": sha(destination)})
    manifest = {"project": project, "verified_upstream_commit": None,
                "source_root": str(source.relative_to(root)), "files": records,
                "patches": []}
    (target / "PROVENANCE.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (target / "MODIFICATIONS.md").write_text("# Local modifications\n\nInitial copy preserves source files. Record patches in PROVENANCE.json.\n")
    verify_project(target, root)
    return target


def record_patch(target: Path, paths: list[str], reason: str) -> None:
    path = target / "PROVENANCE.json"
    manifest = json.loads(path.read_text())
    known = {item["path"] for item in manifest["files"]}
    if not set(paths) <= known:
        raise ValueError("A patch must refer to registered imported files")
    manifest["patches"].append({"reason": reason, "files": [
        {"path": name, "sha256": sha(target / name)} for name in paths]})
    path.write_text(json.dumps(manifest, indent=2) + "\n")


def verify_project(target: Path, root: Path = ROOT) -> None:
    if not (target / "LICENSE").is_file():
        raise ValueError("Missing upstream LICENSE")
    manifest = json.loads((target / "PROVENANCE.json").read_text())
    expected = {item["path"]: item["copied_sha256"] for item in manifest["files"]}
    for patch in manifest["patches"]:
        if not patch.get("reason"):
            raise ValueError("Patch reason is required")
        expected.update({item["path"]: item["sha256"] for item in patch["files"]})
    for item in manifest["files"]:
        if sha(root / item["source"]) != item["source_sha256"]:
            raise ValueError(f"Original source changed: {item['source']}")
        if sha(target / item["path"]) != expected[item["path"]]:
            raise ValueError(f"Unregistered patch: {item['path']}")
    for file in target.rglob("*.py"):
        if "__pycache__" not in file.parts and str(file.relative_to(target)) not in expected:
            raise ValueError(f"Unregistered Python source: {file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("import", "verify"))
    parser.add_argument("project", choices=PROJECTS)
    args = parser.parse_args()
    destination = ROOT / "third_party" / args.project
    if args.command == "import":
        import_project(args.project)
    else:
        verify_project(destination)
    print(f"PASS: {args.command} {args.project}")
