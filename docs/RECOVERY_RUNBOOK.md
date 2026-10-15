# Local encrypted backup and isolated recovery

This is an operator utility, not a web endpoint. Use an owner PostgreSQL connection with pg_dump access, matching PostgreSQL client executables, and the private configured object store. All credentials come from ignored configuration/private session environment. The utility is bounded to local pilot volumes: 128 MiB serialized plaintext maximum, 16 MiB per object and 120 seconds per PostgreSQL subprocess. Missing/corrupt referenced objects abort creation. Database snapshots are consistent; concurrent blob removal may abort and require retry. Temporary plaintext dump files are owner-only and removed when the command exits normally; use an encrypted temporary volume and inspect leftovers after a machine crash.

Initialize a separate backup key once. Never put it in the archive directory or repository. Preserve a private independent recovery copy; the database/source-credential keyring is a separate dependency and must also be recovered for connectors. At most three key versions can be loaded; retain old versions while their archives are unexpired.

```sh
uv run python scripts/backup_pilot.py init-key --key-file .runtime/backup-keys.json
uv run python scripts/backup_pilot.py create --key-file .runtime/backup-keys.json --archive .runtime/backups/snapshot-unique.enc
uv run python scripts/backup_pilot.py journal --key-file .runtime/backup-keys.json --archive .runtime/deletion-receipts/current.enc
uv run python scripts/backup_pilot.py prune --key-file .runtime/backup-keys.json --archive .runtime/backups
```

Creation refuses an existing archive. Journal export intentionally atomically replaces the designated current receipt. Copy encrypted archives and the newest receipt to independently controlled off-host storage; preserve the key separately. Schedule creation at least daily, receipt preservation after every deletion, and expiry pruning daily. These hosted custody/scheduling steps are not deployed by this local utility; SKR-073 stays pending until verified. Default archive expiry is seven days; --days can select 1–30. Pruning fails closed on an invalid archive or unavailable old key instead of deleting unverified files. Restore refuses expired archives.

Create an empty database named skriller_restore_<unique lowercase suffix> on the isolated loopback rehearsal instance. The restricted skriller_app role must already exist with the configured application password. Set SKRILLER_RESTORE_DATABASE_URL and SKRILLER_RESTORE_APPLICATION_DATABASE_URL in the private process environment to that target, leaving the source URL in normal ignored configuration. Select a nonexistent restored-object directory.

```sh
uv run python scripts/backup_pilot.py restore --key-file .runtime/backup-keys.json --archive .runtime/backups/snapshot-unique.enc --restore-objects .runtime/recovery-unique/objects
```

For source-database loss, add --journal-file <independently preserved encrypted current receipt> --journal-is-current. The latter is the operator's assertion that no later deletion is omitted; a historical receipt cannot prove currency. The receipt must match the source fingerprint and postdate the snapshot. Missing latest deletion state must block service restoration.

The result is restored_offline. All active restored jobs are cancelled so old queue messages cannot resume them. Broker messages are not backed up; never connect the restored database to an old broker or API while validating. Verify actor membership/revocation and connector/key configuration against current external identity before traffic; re-import/replay any deletion occurring after the receipt cutoff. Inspect evidence counts/digests, job/claim FKs, tenant denial and current migration revision. Failures leave a disposable offline target; discard that rehearsal target and retry from a new empty one. No --clean or source overwrite operation is supported.

LOCAL-BACKUP-RESTORE.json records the actual synthetic rehearsal, including source loss, deletion replay, retained tenant evidence and measured timing. The production targets remain RPO <=24 hours and RTO <=4 hours; repeat at pilot scale with deployed off-host custody before declaring those targets verified.
