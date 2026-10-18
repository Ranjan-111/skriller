"""Bounded encrypted local-pilot backups; restore only into isolated empty databases.

Reuse Agent-Reach private path helpers and the existing versioned AES keyring.
This operator utility never attaches a restored database to a running service.
"""

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import sqlalchemy as sa
from agent_reach.utils.paths import atomic_write_private_text, read_small_text_no_follow
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from skriller.db import Database
from skriller.erasure import journal, replay_erasures
from skriller.jobs.control import cancel
from skriller.storage import EvidenceStorage, LocalBlobBackend, validate_key

LIMIT = 128 * 1024 * 1024
AAD = b"skriller-local-pilot-backup-v1"


def identity(url):
    parsed = sa.engine.make_url(url)
    if parsed.host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Local pilot backup requires a loopback database")
    return hashlib.sha256(f"{parsed.host}:{parsed.port}:{parsed.database}".encode()).hexdigest()


def pg_env(url):
    parsed = sa.engine.make_url(url)
    identity(url)
    # Explicit database settings, without inherited PG service/options overrides.
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    env.update(
        PGHOST=parsed.host or "localhost",
        PGPORT=str(parsed.port or 5432),
        PGUSER=parsed.username or "",
        PGPASSWORD=parsed.password or "",
        PGDATABASE=parsed.database or "",
        PGCONNECT_TIMEOUT="5",
    )
    return env


def tool(bin_directory, name):
    path = Path(bin_directory).absolute() / name
    if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("Explicit PostgreSQL executable required")
    return str(path)


def invoke(arguments, url, *, output=None):
    result = subprocess.run(
        arguments,
        env=pg_env(url),
        stdin=subprocess.DEVNULL,
        stdout=output or subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("PostgreSQL backup operation failed; diagnostic content redacted")


def seal(payload, keyring):
    content = json.dumps(payload, separators=(",", ":")).encode()
    if len(content) > LIMIT:
        raise ValueError("Pilot backup exceeds 128 MiB limit")
    nonce = os.urandom(12)
    ciphertext = AESGCM(keyring.keys[keyring.active]).encrypt(nonce, content, AAD)
    return json.dumps(
        {
            "version": 1,
            "key_version": keyring.active,
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(ciphertext).decode(),
        }
    )


def unseal(path, keyring, *, allow_expired=False):
    try:
        envelope = json.loads(read_small_text_no_follow(path, max_bytes=2 * LIMIT) or "")
        if (
            set(envelope) != {"version", "key_version", "nonce", "ciphertext"}
            or envelope["version"] != 1
        ):
            raise ValueError()
        content = AESGCM(keyring.keys[envelope["key_version"]]).decrypt(
            base64.b64decode(envelope["nonce"], validate=True),
            base64.b64decode(envelope["ciphertext"], validate=True),
            AAD,
        )
        if len(content) > LIMIT:
            raise ValueError()
        payload = json.loads(content)
        if not allow_expired and datetime.fromisoformat(payload["expires_at"]) <= datetime.now(UTC):
            raise ValueError()
        return payload
    except Exception:  # noqa: BLE001 - redact authentication/parser details
        raise ValueError("Backup is invalid, expired, or cannot be decrypted") from None


def export_journal(owner_url, target, keyring):
    """Independent encrypted deletion receipt for disaster recovery.

    Operators must preserve the newest receipt outside the backed-up data volume.
    Receipt currency is an operator gate; a historical receipt cannot prove that
    no subsequent deletion happened. Restore remains offline in either mode.
    """
    engine = sa.create_engine(owner_url)
    try:
        with engine.connect() as connection:
            rows = [dict(row) for row in connection.execute(sa.select(journal)).mappings()]
        for row in rows:
            row["created_at"] = row["created_at"].isoformat()
        now = datetime.now(UTC)
        payload = {
            "kind": "deletion_journal",
            "source": identity(owner_url),
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(days=30)).isoformat(),
            "rows": rows,
        }
        atomic_write_private_text(target, seal(payload, keyring))
        return {
            "journal_records": len(rows),
            "created_at": now.isoformat(),
            "key_version": keyring.active,
        }
    finally:
        engine.dispose()


def prune_backups(directory, keyring):
    """Physically remove only authenticated expired .enc archives, at most 100."""
    from agent_reach.utils.paths import ensure_no_symlink_path

    directory = ensure_no_symlink_path(directory, "Backup retention")
    removed = 0
    for path in sorted(directory.glob("*.enc"))[:100]:
        payload = unseal(path, keyring, allow_expired=True)
        if datetime.fromisoformat(payload["expires_at"]) <= datetime.now(UTC):
            path.unlink()
            removed += 1
    return {"expired_archives_removed": removed}


def create_backup(owner_url, object_directory, target, keyring, bin_directory, *, days=7):
    if not 1 <= days <= 30:
        raise ValueError("Backup expiry must be 1–30 days")
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise ValueError("Refusing to replace an existing backup")
    started = time.monotonic()
    created = datetime.now(UTC)
    source = identity(owner_url)
    backend = LocalBlobBackend(object_directory)
    engine = sa.create_engine(owner_url)
    try:
        with (
            engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection,
            connection.begin(),
        ):
            snapshot = connection.execute(sa.text("SELECT pg_export_snapshot()")).scalar_one()
            with tempfile.TemporaryDirectory(prefix="skriller-backup-") as temporary:
                dump = Path(temporary) / "database.dump"
                with dump.open("xb") as stream:
                    os.chmod(dump, 0o600)
                    invoke(
                        [
                            tool(bin_directory, "pg_dump"),
                            "--format=custom",
                            "--no-owner",
                            f"--snapshot={snapshot}",
                        ],
                        owner_url,
                        output=stream,
                    )
                if dump.stat().st_size > LIMIT // 2:
                    raise ValueError("Database dump exceeds pilot limit")
                blobs = []
                total = dump.stat().st_size
                for row in connection.execute(
                    sa.text(
                        "SELECT workspace_id,object_key,content_hash FROM evidence WHERE object_key IS NOT NULL"
                    )
                ).mappings():
                    workspace = str(row["workspace_id"])
                    validate_key(workspace, row["object_key"])
                    content = backend.get(workspace, row["object_key"], 16 * 1024 * 1024)
                    total += len(content)
                    if total > LIMIT // 2:
                        raise ValueError("Database and objects exceed pilot limit")
                    if hashlib.sha256(content).hexdigest() != row["content_hash"]:
                        raise ValueError("Cannot back up corrupt evidence")
                    blobs.append(
                        {
                            "workspace": workspace,
                            "key": row["object_key"],
                            "sha256": row["content_hash"],
                            "content": base64.b64encode(content).decode(),
                        }
                    )
                payload = {
                    "source": source,
                    "created_at": created.isoformat(),
                    "expires_at": (created + timedelta(days=days)).isoformat(),
                    "database": base64.b64encode(dump.read_bytes()).decode(),
                    "blobs": blobs,
                }
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        atomic_write_private_text(target, seal(payload, keyring))
        return {
            "created_at": payload["created_at"],
            "expires_at": payload["expires_at"],
            "key_version": keyring.active,
            "objects": len(blobs),
            "backup_seconds": round(time.monotonic() - started, 3),
        }
    finally:
        engine.dispose()


def restore_backup(
    path,
    keyring,
    source_owner_url,
    target_owner_url,
    target_application_url,
    object_directory,
    bin_directory,
    *,
    journal_path=None,
    journal_is_current=False,
):
    """Fresh deletion journal is mandatory; source outage fails closed.

    Target remains offline. Run again from a fresh empty target for another rehearsal.
    No queue is restored; all active jobs are cancelled before any traffic is possible.
    """
    started = time.monotonic()
    payload = unseal(path, keyring)
    receipt = None
    if journal_path:
        receipt = unseal(journal_path, keyring)
        if (
            not journal_is_current
            or receipt.get("kind") != "deletion_journal"
            or receipt.get("source") != payload["source"]
            or datetime.fromisoformat(receipt["created_at"])
            < datetime.fromisoformat(payload["created_at"])
        ):
            raise ValueError("Recovery needs the independently preserved newest deletion receipt")
    target_url = sa.engine.make_url(target_owner_url)
    if (
        identity(source_owner_url) != payload["source"]
        or identity(target_owner_url) == payload["source"]
        or identity(target_application_url) != identity(target_owner_url)
        or not re.fullmatch(r"skriller_restore_[a-z0-9_]{1,48}", target_url.database or "")
    ):
        raise ValueError("Restore requires a matching source and an isolated rehearsal target")
    directory = Path(object_directory).absolute()
    if directory.exists() or directory.is_symlink():
        raise ValueError("Restore requires a fresh object directory")
    source = sa.create_engine(source_owner_url)
    target = sa.create_engine(target_owner_url)
    try:
        with target.connect() as connection:
            if connection.execute(
                sa.text(
                    "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public'"
                )
            ).scalar_one():
                raise ValueError("Restore database must be empty")
        # Validate every object before mutating the target.
        for blob in payload["blobs"]:
            validate_key(blob["workspace"], blob["key"])
            content = base64.b64decode(blob["content"], validate=True)
            if hashlib.sha256(content).hexdigest() != blob["sha256"]:
                raise ValueError("Backup object digest mismatch")
        with tempfile.TemporaryDirectory(prefix="skriller-restore-") as temporary:
            dump = Path(temporary) / "database.dump"
            dump.write_bytes(base64.b64decode(payload["database"], validate=True))
            os.chmod(dump, 0o600)
            invoke(
                [
                    tool(bin_directory, "pg_restore"),
                    "--exit-on-error",
                    "--single-transaction",
                    "--no-owner",
                    "--dbname=" + (target_url.database or ""),
                    str(dump),
                ],
                target_owner_url,
            )
        config = Config("alembic.ini")
        config.attributes["database_url"] = target_owner_url
        command.upgrade(config, "head")
        backend = LocalBlobBackend(directory)
        for blob in payload["blobs"]:
            backend.put(
                blob["workspace"], blob["key"], base64.b64decode(blob["content"], validate=True)
            )
        # Obtain current markers AFTER restoration, rather than trusting the old backup.
        if receipt is None:
            with source.connect() as connection:
                latest = [dict(row) for row in connection.execute(sa.select(journal)).mappings()]
        else:
            latest = receipt["rows"]
            for row in latest:
                row["created_at"] = datetime.fromisoformat(row["created_at"])
        with target.begin() as connection:
            # Archived paid-access leases cannot establish current provider truth.
            # Preserve authority bindings, but require fresh reconciliation.
            connection.execute(
                sa.text(
                    "UPDATE billing_bindings SET enabled=false,valid_until=NULL,updated_at=clock_timestamp()"
                )
            )
            connection.execute(
                sa.text(
                    "UPDATE billing_checkout_intents SET checkout_url=NULL,state=CASE "
                    "WHEN state IN ('dispatching','ready') THEN 'uncertain' ELSE state END"
                )
            )
            connection.execute(
                sa.text(
                    "UPDATE crm_destinations SET enabled=false,ciphertext=''::bytea,generation=generation+1"
                )
            )
            connection.execute(
                sa.text(
                    "UPDATE crm_deliveries SET state='cancelled',last_code='restored',lease_token=NULL,"
                    "lease_expires_at=NULL WHERE state IN ('pending','delivering')"
                )
            )
            # OAuth consent cannot be revived from an old archive, including
            # grants belonging to other owners of the same workspace.
            connection.execute(
                sa.text(
                    "UPDATE youtube_analytics_grants SET state='revoked',state_hash=NULL,"
                    "ciphertext=''::bytea,version=version+1"
                )
            )
            connection.execute(
                sa.text(
                    "UPDATE crm_oauth_consents SET state='revoked',state_hash=NULL,"
                    "ciphertext=''::bytea,version=version+1"
                )
            )
            connection.execute(
                sa.text(
                    "UPDATE x_oauth_consents SET state='revoked',state_hash=NULL,"
                    "ciphertext=''::bytea,version=version+1"
                )
            )
            connection.execute(
                sa.text(
                    "UPDATE reddit_oauth_consents SET state='revoked',state_hash=NULL,"
                    "ciphertext=''::bytea,version=version+1"
                )
            )
            connection.execute(sa.text("DELETE FROM reddit_search_continuations"))
            restored_workspaces = {
                str(value)
                for value in connection.execute(sa.text("SELECT id FROM workspaces")).scalars()
            }
            for row in latest:
                from sqlalchemy.dialects.postgresql import insert

                if row["workspace_id"] in restored_workspaces:
                    connection.execute(insert(journal).values(**row).on_conflict_do_nothing())
            owners = connection.execute(
                sa.text(
                    "SELECT DISTINCT ON (workspace_id) workspace_id,actor_id FROM memberships "
                    "WHERE role='owner' ORDER BY workspace_id,actor_id"
                )
            ).all()
            missing = connection.execute(
                sa.text(
                    "SELECT count(*) FROM workspaces w WHERE NOT EXISTS "
                    "(SELECT 1 FROM memberships m WHERE m.workspace_id=w.id AND m.role='owner')"
                )
            ).scalar_one()
            if missing:
                raise ValueError("Restored workspace is missing an owner")
        database = Database(target_application_url)
        replayed = 0
        storage = EvidenceStorage(backend)
        try:
            for workspace, actor in owners:
                with database.tenant(actor, str(workspace)) as session:
                    active = (
                        session.execute(
                            sa.text(
                                "SELECT id FROM jobs WHERE state IN ('planned','queued','running','paused','waiting_for_connection')"
                            )
                        )
                        .scalars()
                        .all()
                    )
                    for job in active:
                        cancel(session, str(job))
                    from skriller.automation_lifecycle import quarantine

                    quarantine(session, "restore_requires_opt_in")
                    replayed += replay_erasures(session, storage)
            # Verify every remaining private pointer and claim FK in the restored database.
            with target.connect() as connection:
                for row in connection.execute(
                    sa.text(
                        "SELECT workspace_id,object_key,content_hash FROM evidence WHERE object_key IS NOT NULL"
                    )
                ).mappings():
                    content = backend.get(
                        str(row["workspace_id"]), row["object_key"], 16 * 1024 * 1024
                    )
                    if hashlib.sha256(content).hexdigest() != row["content_hash"]:
                        raise ValueError("Restored evidence consistency failure")
        finally:
            database.dispose()
        return {
            "status": "restored_offline",
            "objects": len(payload["blobs"]),
            "replayed_entities": replayed,
            "workspaces": len(owners),
            "snapshot_age_seconds": round(
                (datetime.now(UTC) - datetime.fromisoformat(payload["created_at"])).total_seconds(),
                3,
            ),
            "restore_seconds": round(time.monotonic() - started, 3),
            "traffic_enabled": False,
        }
    finally:
        source.dispose()
        target.dispose()
