"""Export actual API/DTO schema for frontend type generation and drift checks."""

import argparse
import json
from pathlib import Path

from skriller.api import create_app
from skriller.settings import Settings

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    serialized = (
        json.dumps(create_app(Settings(environment="test")).openapi(), indent=2, sort_keys=True)
        + "\n"
    )
    if args.check:
        if not args.output.is_file() or args.output.read_text() != serialized:
            parser.exit(1, "Generated API contract differs; regenerate and type-check the client\n")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized)
