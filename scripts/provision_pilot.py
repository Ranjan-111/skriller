"""Operator-only manual pilot allowance; no billing, provider IO or usage reset."""

import argparse
import json
from uuid import UUID

import sqlalchemy as sa

from skriller.entitlements import provision_manual_pilot as provision
from skriller.settings import Settings

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=UUID, required=True)
    parser.add_argument("--runs", type=int, required=True)
    parser.add_argument("--results", type=int, required=True)
    parser.add_argument("--sources", type=int, required=True)
    parser.add_argument("--invoice-reference", required=True)
    args = parser.parse_args()
    engine = sa.create_engine(Settings().database_url)
    try:
        with engine.begin() as connection:
            print(
                json.dumps(
                    provision(
                        connection,
                        args.workspace,
                        runs=args.runs,
                        results=args.results,
                        sources=args.sources,
                        invoice_reference=args.invoice_reference,
                    )
                )
            )
    finally:
        engine.dispose()
