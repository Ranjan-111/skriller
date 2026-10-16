"""Explicit per-workspace notification worker; disabled unless operator starts it."""

import argparse
import json
import sys
import time
from pathlib import Path
from uuid import UUID

from agent_reach.utils.process import utf8_subprocess_env

from skriller.connections.keys import Keyring
from skriller.db import Database
from skriller.security.runner import bounded_process
from skriller.settings import Settings
from skriller.webhooks.service import claim, deliver


def run_delivery_child(actor_id, workspace_id, task):
    # No secret, endpoint URL, research text, or key material crosses argv/pipes.
    argv = [
        sys.executable,
        "-m",
        "skriller.webhooks.runtime",
        "--workspace-id",
        str(UUID(workspace_id)),
        "--actor-id",
        actor_id,
        "--delivery-id",
        str(UUID(task["delivery_id"])),
        "--endpoint-id",
        str(UUID(task["endpoint_id"])),
        "--lease-token",
        str(UUID(task["lease_token"])),
    ]
    result = bounded_process(
        argv, cwd=Path.cwd(), env=utf8_subprocess_env(), timeout=20, max_output=4096
    )
    if result.status != "completed" or result.returncode != 0:
        return "uncertain"  # reserved attempt remains durable; retry only after lease expiry
    try:
        data = json.loads(result.stdout)
        if data not in {"stale_lease", "cancelled", "delivered", "pending", "failed", "blocked"}:
            return "uncertain"
        return data
    except (ValueError, TypeError):
        return "uncertain"


def run_once(database, actor_id, workspace_id):
    with database.tenant(actor_id, workspace_id) as session:
        task = claim(session)
    if task is None:
        return "idle"
    return run_delivery_child(actor_id, workspace_id, task)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=True, type=UUID)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--delivery-id", type=UUID)
    parser.add_argument("--endpoint-id", type=UUID)
    parser.add_argument("--lease-token", type=UUID)
    args = parser.parse_args()
    is_child = args.delivery_id is not None
    if any((args.delivery_id, args.endpoint_id, args.lease_token)) and not all(
        (args.delivery_id, args.endpoint_id, args.lease_token)
    ):
        parser.error("Delivery identity requires all three IDs")
    settings = Settings()
    database = Database(settings.application_database_url)
    try:
        ring = Keyring.load(settings.source_encryption_key_file)
        if is_child:
            task = {
                "delivery_id": str(args.delivery_id),
                "endpoint_id": str(args.endpoint_id),
                "lease_token": str(args.lease_token),
            }
            with database.tenant(args.actor_id, str(args.workspace_id)) as session:
                state = deliver(session, task, ring)
            print(json.dumps(state))
            return
        while True:
            result = run_once(database, args.actor_id, str(args.workspace_id))
            if args.once:
                return
            time.sleep(5 if result == "idle" else 1)
    except Exception:  # noqa: BLE001 - never print credentials/URLs/transport traces
        raise SystemExit(
            "Webhook worker unavailable; verify owner access and private key configuration"
        ) from None
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
