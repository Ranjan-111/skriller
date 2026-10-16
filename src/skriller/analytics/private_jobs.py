"""Owner-private, encrypted report snapshots for metered summary execution.

Only opaque references belong in shared job records. This store deliberately does
not enqueue a normal research worker or accept client-supplied report contents.
"""

import json
import os
from datetime import UTC, timedelta
from uuid import UUID

import sqlalchemy as sa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from skriller.analytics.google import AnalyticsUnavailable
from skriller.analytics.reports import AnalyticsReport, VerifiedReport
from skriller.analytics.service import now
from skriller.analytics.tables import summary_jobs
from skriller.db import JobRepository
from skriller.db.repositories import insert_row, require_owner, scope
from skriller.jobs.budget import locked_job
from skriller.jobs.control import permit_call


class PrivateSummaryStore:
    def __init__(self, grants):
        self.grants = grants
        self.ring = grants.ring

    @staticmethod
    def _aad(row):
        return json.dumps(
            [
                "skriller-private-analytics-summary-v1",
                row["workspace_id"],
                row["id"],
                row["created_by"],
                row["grant_id"],
                row["grant_version"],
                row["key_version"],
                row["expires_at"].astimezone(UTC).isoformat(),
                row["state"],
            ],
            separators=(",", ":"),
        ).encode()

    def _seal(self, row, value):
        payload = json.dumps(value, separators=(",", ":")).encode()
        if len(payload) > 65500:
            raise ValueError("Private summary payload exceeds limit")
        nonce = os.urandom(12)
        return {
            "nonce": nonce,
            "ciphertext": AESGCM(self.ring.keys[row["key_version"]]).encrypt(
                nonce, payload, self._aad(row)
            ),
        }

    def _open(self, row):
        try:
            return json.loads(
                AESGCM(self.ring.keys[row["key_version"]]).decrypt(
                    row["nonce"], row["ciphertext"], self._aad(row)
                )
            )
        except Exception:  # noqa: BLE001 - no private payload/key details in errors
            raise AnalyticsUnavailable() from None

    def get(self, session, job_id, *, lock=False):
        require_owner(session)
        query = sa.select(summary_jobs).where(
            summary_jobs.c.workspace_id == scope(session),
            summary_jobs.c.id == str(UUID(str(job_id))),
            summary_jobs.c.created_by == session.info["actor_id"],
        )
        if lock:
            query = query.with_for_update()
        row = session.execute(query).mappings().one_or_none()
        if row is None or row["expires_at"] <= now(session):
            raise AnalyticsUnavailable()
        self.grants.recheck(session, row["grant_id"], row["grant_version"])
        return dict(row)

    def save(self, session, job_id, verified: VerifiedReport, *, request=None):
        """Bind a trusted report once to an owner-created, executable metered job."""
        require_owner(session)
        if verified.owner_id != session.info["actor_id"] or verified.workspace_id != scope(session):
            raise AnalyticsUnavailable()
        locked_job(session, str(job_id))
        grant = self.grants.get(session, verified.report.grant_id, lock=True)
        self.grants.recheck(session, verified.report.grant_id, verified.grant_version)
        job = JobRepository.get(session, str(job_id))
        if (
            not job
            or job["created_by"] != verified.owner_id
            or not permit_call(session, str(job_id))
        ):
            raise AnalyticsUnavailable()
        # Serialize repeated submission on the existing shared accounting job.
        session.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "private-analytics-summary:" + str(job_id)},
        )
        existing = (
            session.execute(
                sa.select(summary_jobs).where(
                    summary_jobs.c.workspace_id == scope(session), summary_jobs.c.id == str(job_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        payload = {"report": verified.report.model_dump(mode="json")}
        if request is not None:
            payload["request"] = request
        if existing:
            current = self.get(session, job_id)
            if self._open(current)["report"] != payload["report"]:
                raise ValueError("Summary job already bound to another report")
            return current
        row = {
            "workspace_id": scope(session),
            "id": str(job_id),
            "created_by": verified.owner_id,
            "grant_id": str(verified.report.grant_id),
            "grant_version": verified.grant_version,
            "key_version": self.ring.active,
            "state": "queued",
            "expires_at": min(now(session) + timedelta(hours=1), grant["expires_at"]),
        }
        return insert_row(
            session,
            summary_jobs,
            **{k: v for k, v in row.items() if k != "workspace_id"},
            **self._seal(row, payload),
        )

    def report(self, session, job_id):
        row = self.get(session, job_id)
        report = AnalyticsReport.model_validate(self._open(row)["report"])
        return VerifiedReport(report, row["created_by"], row["workspace_id"], row["grant_version"])

    def cancel(self, session, job_id):
        row = self.get(session, job_id, lock=True)
        if row["state"] in {"completed", "failed", "cancelled"}:
            return row["state"]
        session.execute(
            sa.update(summary_jobs)
            .where(summary_jobs.c.workspace_id == scope(session), summary_jobs.c.id == row["id"])
            .values(state="cancelled", ciphertext=b"")
        )
        return "cancelled"

    def discard(self, session, job_id):
        """Wipe interrupted output even when consent has already become unusable."""
        require_owner(session)
        session.execute(
            sa.update(summary_jobs)
            .where(
                summary_jobs.c.workspace_id == scope(session),
                summary_jobs.c.id == str(job_id),
                summary_jobs.c.created_by == session.info["actor_id"],
                summary_jobs.c.state != "cancelled",
            )
            .values(state="failed", ciphertext=b"")
        )

    def result(self, session, job_id):
        row = self.get(session, job_id)
        if row["state"] != "completed":
            return {"state": row["state"], "result": None}
        return {"state": "completed", "result": self._open(row)["result"]}

    async def execute(self, database, context, *, model=None):
        """Claim once before model IO; uncertain executions are never replayed.

        A caller must supply the matching opaque accounting context. Private
        answers are encrypted here, never saved as workspace evidence/events.
        """
        from dataclasses import asdict

        from skriller.analytics.summaries import summarize_report

        job_id, workspace = str(context.job_id), str(context.workspace_id)
        with database.tenant(context.actor_id, workspace) as session:
            locked_job(session, job_id)
            row = self.get(session, job_id, lock=True)
            if row["state"] != "queued":
                return row["state"]
            if not permit_call(session, job_id):
                return self.cancel(session, job_id)
            payload = self._open(row)
            verified = self.report(session, job_id)
            row["state"] = "running"
            session.execute(
                sa.update(summary_jobs)
                .where(summary_jobs.c.workspace_id == workspace, summary_jobs.c.id == job_id)
                .values(state="running", **self._seal(row, payload))
            )
        # The committed running marker prevents duplicate workers/model charges.
        result = await summarize_report(
            database,
            self.grants,
            context,
            verified,
            operation_key="private-analytics-summary:" + job_id,
            model=model,
        )
        with database.tenant(context.actor_id, workspace) as session:
            locked_job(session, job_id)
            row = self.get(session, job_id, lock=True)
            if row["state"] != "running":
                return row["state"]
            if not permit_call(session, job_id):
                return self.cancel(session, job_id)
            payload = self._open(row)
            payload["result"] = asdict(result)
            row["state"] = "completed"
            session.execute(
                sa.update(summary_jobs)
                .where(summary_jobs.c.workspace_id == workspace, summary_jobs.c.id == job_id)
                .values(state="completed", **self._seal(row, payload))
            )
        return "completed"
