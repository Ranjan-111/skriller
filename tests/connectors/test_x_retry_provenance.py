"""The minimal worker copies the existing upstream Retry-After logic unchanged."""

import ast
from pathlib import Path


def test_retry_after_function_matches_pinned_scrapling_source():
    root = Path(__file__).resolve().parents[2]
    functions = []
    for name in (
        "third_party/scrapling/scrapling/spiders/throttle.py",
        "src/skriller/_vendor/retry_after.py",
    ):
        tree = ast.parse((root / name).read_text())
        functions.append(
            next(
                n
                for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "parse_retry_after"
            )
        )
    assert ast.dump(functions[0]) == ast.dump(functions[1])
    assert (root / "third_party/scrapling/LICENSE").is_file()
