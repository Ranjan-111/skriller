"""Operator-only local backup/rehearsal CLI; credentials come from ignored env."""

import argparse
import json
import os
from pathlib import Path

from skriller.backups import create_backup, export_journal, prune_backups, restore_backup
from skriller.connections.keys import Keyring
from skriller.settings import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["init-key", "create", "restore", "journal", "prune"])
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--archive")
    parser.add_argument("--pg-bin", default=".runtime/postgres/bin")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--restore-objects")
    parser.add_argument("--journal-file")
    parser.add_argument("--journal-is-current", action="store_true")
    arguments = parser.parse_args()
    try:
        if arguments.operation == "init-key":
            Keyring.create_file(arguments.key_file)
            print("Private backup key initialized; keep a separate recovery copy.")
            return
        if not arguments.archive:
            parser.error("--archive is required")
        settings = Settings()
        if arguments.operation in {"create", "restore"} and settings.object_backend != "local":
            raise SystemExit(
                "Local backup/rehearsal requires the local object backend; "
                "remote object backup and restore verification remain pending."
            )
        ring = Keyring.load(arguments.key_file)
        if arguments.operation == "journal":
            report = export_journal(settings.database_url, arguments.archive, ring)
        elif arguments.operation == "prune":
            report = prune_backups(arguments.archive, ring)
        elif arguments.operation == "create":
            report = create_backup(
                settings.database_url,
                settings.object_directory,
                Path(arguments.archive),
                ring,
                arguments.pg_bin,
                days=arguments.days,
            )
        else:
            owner = os.environ.get("SKRILLER_RESTORE_DATABASE_URL")
            application = os.environ.get("SKRILLER_RESTORE_APPLICATION_DATABASE_URL")
            if not owner or not application or not arguments.restore_objects:
                parser.error(
                    "Set both SKRILLER_RESTORE_*DATABASE_URL variables and --restore-objects"
                )
            report = restore_backup(
                arguments.archive,
                ring,
                settings.database_url,
                owner,
                application,
                arguments.restore_objects,
                arguments.pg_bin,
                journal_path=arguments.journal_file,
                journal_is_current=arguments.journal_is_current,
            )
        print(json.dumps(report))
    except Exception:  # noqa: BLE001 - operator boundary must not print credentials
        raise SystemExit(
            "Operation failed; target remains offline. Check the recovery runbook."
        ) from None


if __name__ == "__main__":
    main()
