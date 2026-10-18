"""Vault-to-runner delivery with generation, revocation and final-output fencing.

Source adapters still own their reservation, capacity, result schema and evidence
transaction. This boundary cannot authorize a command absent from reviewed_command.
"""

from datetime import UTC, datetime
from time import monotonic
from uuid import UUID

from skriller.connections.store import ConnectionStore, ConnectionUnavailable
from skriller.contracts import ExecutionContext
from skriller.security.runner import IsolatedRunner, RunResult


def run_connected(
    database,
    store: ConnectionStore,
    context: ExecutionContext,
    runner: IsolatedRunner,
    operation: str,
    target: str,
    *,
    timeout: float = 60,
    max_output: int = 1024 * 1024,
    expected_credential_ref: UUID | None = None,
) -> RunResult:
    """Load once, poll persisted authority, discard output after authority changes."""
    started = monotonic()

    def stopped(status):
        return RunResult(status, None, "", "Source connection execution is unavailable", 0)

    try:
        with database.tenant(context.actor_id, str(context.workspace_id)) as session:
            material = store.load_for_runner(session, context, operation)
            if (
                expected_credential_ref is not None
                and material.credential_ref != expected_credential_ref
            ) or not store.runner_current(session, context, material):
                return stopped("needs_connection")
    except ConnectionUnavailable:
        return stopped("needs_connection")
    except Exception:  # noqa: BLE001 - never return private control-plane diagnostics
        return stopped("control_unavailable")

    def cancelled():
        with database.tenant(context.actor_id, str(context.workspace_id)) as session:
            return not store.runner_current(session, context, material)

    remaining = (context.deadline - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        return stopped("needs_connection")
    try:
        result = runner.run(
            operation,
            target,
            timeout=min(timeout, remaining),
            max_output=max_output,
            cancel_check=cancelled,
            credential_material=material,
        )
    except Exception:  # noqa: BLE001 - executor exceptions can contain source secrets
        return stopped("unavailable")
    # Run cleanup status must remain visible even when authorization has expired.
    if result.status == "cleanup_failed":
        return RunResult(result.status, result.returncode, "", result.stderr, result.elapsed_ms)
    try:
        invalidated = cancelled()
    except Exception:  # noqa: BLE001 - control-plane diagnostics can contain private configuration
        return RunResult("control_unavailable", result.returncode, "", "", result.elapsed_ms)
    if invalidated:
        return RunResult(
            "needs_connection",
            result.returncode,
            "",
            "Source connection or job changed",
            round((monotonic() - started) * 1000),
        )
    return result
