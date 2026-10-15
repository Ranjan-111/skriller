"""Budgeted public video evidence; captions never resolve creator identity."""

import json
from decimal import Decimal
from time import monotonic
from urllib.parse import urlencode

import sqlalchemy as sa

from skriller.connectors.switches import is_disabled
from skriller.connectors.youtube import YouTubeReadEvidence, _video_id, parse_read_output
from skriller.contracts import Failure
from skriller.db import JobRepository, ResearchRepository
from skriller.db.repositories import scope
from skriller.db.schema import entities
from skriller.erasure import privacy_lock, suppressed
from skriller.jobs.control import permit_call
from skriller.jobs.worker import StageHandler


def youtube_collection_handler(database, identity, attributes, entity_id, storage, reader):
    def permitted():
        with database.tenant(identity.actor_id, str(identity.workspace_id)) as session:
            return permit_call(session, str(identity.job_id)) > 0 and not is_disabled(
                session, "youtube", "read"
            )

    def run(plan, timeout_seconds):
        if reader is None or "youtube" not in plan.sources:
            return (
                (
                    None,
                    Failure(
                        code="unsupported_operation", message="Public video reader is not enabled"
                    ),
                    0,
                ),
                Decimal(0),
                {"fetch_attempts": 0},
            )
        if not permitted():
            return (
                (None, Failure(code="cancelled", message="Public video read was stopped"), 0),
                Decimal(0),
                {"fetch_attempts": 0},
            )
        timeout = min(50, timeout_seconds - 12)
        if timeout <= 0:
            raise TimeoutError("Insufficient worker execution window")
        started = monotonic()
        data = reader.execute(
            attributes["url"], timeout=timeout, cancel_check=lambda: not permitted()
        )
        if not isinstance(data, YouTubeReadEvidence):
            raise TypeError("Typed isolated video result required")
        data = parse_read_output(data.model_dump_json(), requested_url=attributes["url"])
        return (
            (data, None, monotonic() - started),
            Decimal(0),
            {"fetch_attempts": data.request_count},
        )

    def persist(session, result):
        data, failure, elapsed = result
        privacy_lock(session)
        entity = (
            session.execute(
                sa.select(entities)
                .where(
                    entities.c.workspace_id == scope(session),
                    entities.c.id == entity_id,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        native = (
            {"namespace": "youtube_video", "id": _video_id(data.metadata.source_url)}
            if data
            else None
        )
        if (
            entity is None
            or entity["attributes"].get("erased")
            or suppressed(session, entity_id=entity_id, url=attributes["url"])
        ):
            return []
        if native and suppressed(session, native_id=native):
            session.execute(
                sa.update(entities)
                .where(
                    entities.c.workspace_id == scope(session),
                    entities.c.id == entity_id,
                )
                .values(
                    attributes={"erased": True}, display_name=None, canonical_key=None, kind="other"
                )
            )
            return []
        updated = dict(entity["attributes"])
        summary = {"status": "unavailable", "failure_code": failure.code if failure else None}
        if data is not None:
            assert native is not None
            metadata = data.metadata.model_dump(mode="json")
            proof = {key: value for key, value in metadata.items() if key != "description"}
            saved = storage.store(
                session,
                data.model_dump_json().encode(),
                source_url=data.metadata.source_url,
                source_platform="youtube",
                collected_at=data.metadata.observed_at,
                excerpt=json.dumps(proof, ensure_ascii=False, separators=(",", ":")),
            )
            updated["_collection_body_evidence_id"] = saved["id"]
            updated["_source_native_id"] = native
            updated["_source_resource_type"] = "youtube_video"
            observations: list[dict] = []
            preview: list[dict] = []

            def observe(field, value, quote, record):
                claim = ResearchRepository.claim(
                    session,
                    entity_id,
                    field,
                    value,
                    mode="observed",
                    status="accepted",
                    evidence_ids=[record["id"]],
                )
                observations.append(
                    {
                        "claim_id": claim["id"],
                        "field": field,
                        "value": value,
                        "quote": quote,
                        "status": claim["status"],
                    }
                )
                return claim

            for key, field in (
                ("title", "youtube_video_title"),
                ("view_count", "youtube_public_view_count"),
                ("like_count", "youtube_public_like_count"),
                ("duration_seconds", "youtube_duration_seconds"),
            ):
                value = metadata[key]
                if value is not None:
                    observe(
                        field,
                        value,
                        json.dumps({key: value}, ensure_ascii=False, separators=(",", ":"))[1:-1],
                        saved,
                    )
            for index, segment in enumerate(data.segments):
                if len(preview) >= 20:
                    break
                if len(segment.text) > 4000:
                    continue
                quote = f"[{segment.start_seconds:.3f}s–{segment.end_seconds:.3f}s] {segment.text}"
                source = "https://www.youtube.com/watch?" + urlencode(
                    {"v": native["id"], "t": int(segment.start_seconds)}
                )
                record = storage.store(
                    session,
                    quote.encode(),
                    source_url=source,
                    source_platform="youtube",
                    collected_at=segment.observed_at,
                    excerpt=quote,
                )
                claim = observe(f"youtube_caption_{index}", segment.text, quote, record)
                preview.append(
                    {
                        "start_seconds": segment.start_seconds,
                        "end_seconds": segment.end_seconds,
                        "text": segment.text,
                        "evidence_id": record["id"],
                        "claim_id": claim["id"],
                    }
                )
            updated["youtube"] = {
                "metadata": metadata,
                "metadata_truncated": data.metadata_truncated,
                "caption_status": data.caption_status,
                "caption_origin": data.caption_origin,
                "caption_language": data.caption_language,
                "segments": preview,
                "omitted_segments": len(data.segments) - len(preview),
                "subject_identity": "unknown",
                "evidence_expired": False,
            }
            updated["extraction"] = {
                "status": "observed",
                "failure_code": None,
                "observations": observations,
                "rejected_claims": 0,
                "coverage_complete": False,
                "omitted_chunks": len(data.segments) - len(preview),
            }
            summary.update(
                status="read",
                failure_code=None,
                observed_at=data.metadata.observed_at.isoformat(),
                final_url=data.metadata.source_url,
                content_hash=saved["content_hash"],
                coverage_complete=False,
                prepared_chunks=0,
            )
        updated["collection"] = summary
        session.execute(
            sa.update(entities)
            .where(entities.c.workspace_id == scope(session), entities.c.id == entity_id)
            .values(attributes=updated)
        )
        JobRepository.event(
            session,
            str(identity.job_id),
            f"collection:{identity.attempt_id}",
            "collection_summary",
            {
                "entity_id": entity_id,
                "source": "youtube",
                "status": summary["status"],
                "failure_code": summary["failure_code"],
                "provider_io_seconds": elapsed,
            },
        )
        return [entity_id]

    return StageHandler(
        run,
        persist,
        Decimal(0),
        {"fetch_attempts": 12 if reader is not None else 0},
        lease_seconds=70,
        run_with_deadline=run,
        capacity_kind="http",
        capacity_source="youtube",
        capacity_host="www.youtube.com",
        minimum_interval=1,
        feedback_failure=lambda data: data[1],
    )
