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
    parser.add_argument("--service", choices=("main", "billing"), default="main")
    args = parser.parse_args()
    if args.service == "billing":
        from fastapi import FastAPI

        from skriller.billing.checkout_router import router

        app = FastAPI(title="Skriller billing checkout", version="0.1.0")
        app.include_router(router)
    else:
        app = create_app(Settings(environment="test"))
    serialized = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not args.output.is_file() or args.output.read_text() != serialized:
            parser.exit(1, "Generated API contract differs; regenerate and type-check the client\n")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized)
